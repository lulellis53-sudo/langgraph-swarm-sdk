"""Analytics + vector ingest for harvested BR price observations.

Pipeline stages (each one small and independently callable):

- ``polars_stage``: load observations into Polars, dedupe, aggregate daily
  floor/median/mean per SKU and condition.
- ``numpy_stage``: per-SKU daily-floor series as float arrays with stats.
- ``sympy_stage``: symbolic linear trend per SKU (``price(t) = a*t + b``).
- ``vector_stage``: embed each deduped observation with the deterministic
  LexicalEmbedder and upsert into a ``sqlite-vec`` virtual table for
  semantic price lookup (``nearest_prices``).
- ``graph_stage``: one PNG with a price-per-day subplot per SKU.

Run with the WebSearch venv (LexicalEmbedder lives in the Swarm lane):
    uv run --project ~/Swarm/WebSearch python ~/Swarm-Prediction/Prediction/ingest.py
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
#: LexicalEmbedder (numpy feature-hashing) lives in the Swarm checkout.
sys.path.insert(0, str(Path.home() / "Swarm"))

from Prediction.br_hardware import PRODUCTS  # noqa: E402

_PKG_DIR = Path(__file__).resolve().parent
DB_PATH = _PKG_DIR / "offers.db"
GRAPHS_DIR = _PKG_DIR / "graphs"
EMBED_DIM = 1024

SKU_NAMES = {p.sku: p.name for p in PRODUCTS}


def polars_stage(conn: sqlite3.Connection) -> pl.DataFrame:
    """Load, normalize, and dedupe observations; return the daily aggregate."""
    rows = [
        tuple(r)
        for r in conn.execute(
            """
            SELECT sku, source, url, observed_on, amount_cents, payment, condition,
                   verification, data_origin
            FROM price_observations
            """
        ).fetchall()
    ]
    frame = pl.DataFrame(
        rows,
        schema={
            "sku": pl.String,
            "source": pl.String,
            "url": pl.String,
            "observed_on": pl.String,
            "amount_cents": pl.Int64,
            "payment": pl.String,
            "condition": pl.String,
            "verification": pl.String,
            "data_origin": pl.String,
        },
        orient="row",
    )
    # Normalizer: canonical columns, BRL price, sorted dates.
    frame = frame.with_columns(
        (pl.col("amount_cents") / 100.0).alias("price_brl"),
        pl.col("observed_on").str.to_date("%Y-%m-%d"),
    ).sort("observed_on")
    # Dedupe: same URL listed at the same price twice (recrawls, mirrors).
    deduped = frame.unique(["sku", "source", "url", "amount_cents", "observed_on"], keep="first")
    return (
        deduped.group_by("sku", "observed_on", "condition")
        .agg(
            pl.col("price_brl").min().alias("floor"),
            pl.col("price_brl").median().alias("median"),
            pl.col("price_brl").mean().alias("mean"),
            pl.len().alias("n"),
        )
        .sort("observed_on")
    )


def numpy_stage(daily: pl.DataFrame) -> dict[str, dict[str, np.ndarray]]:
    """Per-SKU floor series as arrays: dates (ordinal) and BRL values."""
    out: dict[str, dict[str, np.ndarray]] = {}
    for sku in daily["sku"].unique():
        sub = daily.filter((pl.col("sku") == sku) & (pl.col("condition") == "new"))
        if sub.is_empty():
            continue
        out[sku] = {
            # datetime64[D] as int64 is days since the epoch.
            "t": np.array(sub["observed_on"].to_list(), dtype="datetime64[D]").astype(np.int64),
            "floor": np.array(sub["floor"].to_list(), dtype=float),
            "median": np.array(sub["median"].to_list(), dtype=float),
        }
    return out


def sympy_stage(series: dict[str, dict[str, np.ndarray]]) -> dict[str, str]:
    """Symbolic linear trend per SKU from the NumPy floor series."""
    import sympy as sp

    t_sym = sp.Symbol("t", real=True)
    equations: dict[str, str] = {}
    for sku, data in series.items():
        if len(data["t"]) < 2:
            equations[sku] = "insufficient history"
            continue
        slope, intercept = np.polyfit(data["t"], data["floor"], 1)
        expr = sp.N(slope, 4) * t_sym + sp.N(intercept, 6)
        equations[sku] = f"price(t) = {sp.simplify(expr)}"
    return equations


def _embed(text: str, embedder) -> bytes:
    vector = embedder.embed([text])[0]
    return np.asarray(vector, dtype=np.float32).tobytes()


def vector_stage(conn: sqlite3.Connection) -> int:
    """Upsert deduped observations into a sqlite-vec table (semantic lookup)."""
    import sqlite_vec
    from Prediction.mcp_server import load_lexical_embedder

    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.execute(
        f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS price_vectors USING vec0(
            embedding float[{EMBED_DIM}]
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS price_vector_meta(
            vec_rowid INTEGER PRIMARY KEY,
            sku TEXT, source TEXT, observed_on TEXT, condition TEXT,
            amount_cents INTEGER, url TEXT
        )
        """
    )
    rows = conn.execute(
        """
        SELECT rowid, sku, source, url, observed_on, amount_cents, condition
        FROM price_observations
        """
    ).fetchall()
    embedder = load_lexical_embedder(EMBED_DIM)
    existing = {r[0] for r in conn.execute("SELECT vec_rowid FROM price_vector_meta")}
    written = 0
    for row in rows:
        rowid, sku, source, url, day, cents, condition = row
        if rowid in existing:
            continue
        text = f"{SKU_NAMES.get(sku, sku)} {source} {condition} {day} BRL {cents / 100:.2f}"
        conn.execute(
            "INSERT INTO price_vectors(rowid, embedding) VALUES (?, ?)",
            (rowid, _embed(text, embedder)),
        )
        conn.execute(
            """
            INSERT INTO price_vector_meta(
                vec_rowid, sku, source, observed_on, condition, amount_cents, url
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (rowid, sku, source, day, condition, cents, url),
        )
        written += 1
    conn.commit()
    return written


def nearest_prices(conn: sqlite3.Connection, query: str, k: int = 5) -> list[dict]:
    """K-nearest price observations for a natural-language query."""
    import sqlite_vec
    from WebSearch.backend.semantic import LexicalEmbedder

    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    embedder = LexicalEmbedder(dim=EMBED_DIM)
    vector = _embed(query, embedder)
    rows = conn.execute(
        """
        SELECT m.sku, m.source, m.observed_on, m.condition, m.amount_cents, m.url,
               distance
        FROM price_vectors v
        JOIN price_vector_meta m ON m.vec_rowid = v.rowid
        WHERE embedding MATCH ? AND k = ?
        ORDER BY distance
        """,
        (vector, k),
    ).fetchall()
    keys = ("sku", "source", "day", "condition", "amount_cents", "url", "distance")
    return [dict(zip(keys, row)) for row in rows]


def graph_stage(series: dict[str, dict[str, np.ndarray]], out_dir: Path) -> Path:
    """Render one PNG with a floor/median subplot per SKU."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    out_dir.mkdir(parents=True, exist_ok=True)
    skus = list(series)
    cols = 3
    rows = (len(skus) + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(5 * cols, 3.2 * rows), squeeze=False)
    for index, sku in enumerate(skus):
        ax = axes[index // cols][index % cols]
        data = series[sku]
        days = (data["t"] * 86_400).astype("datetime64[s]")
        ax.plot(days, data["floor"], marker="o", label="floor")
        ax.plot(days, data["median"], marker="s", alpha=0.6, label="median")
        ax.set_title(f"{SKU_NAMES.get(sku, sku)}", fontsize=9)
        ax.yaxis.set_major_formatter(lambda x, _: f"R${x:,.0f}")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
        ax.tick_params(labelsize=7)
        ax.legend(fontsize=7)
    for spare in axes.flat[len(skus) :]:
        spare.axis("off")
    fig.autofmt_xdate()
    fig.tight_layout()
    out = out_dir / "prices.png"
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


def main() -> int:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    daily = polars_stage(conn)
    print(f"polars: {daily.height} sku/day rows (deduped aggregate)")
    series = numpy_stage(daily)
    print(f"numpy: {len(series)} sku series")
    for sku, equation in sympy_stage(series).items():
        print(f"sympy: {sku:<12} {equation}")
    written = vector_stage(conn)
    total = conn.execute("SELECT COUNT(*) FROM price_vector_meta").fetchone()[0]
    print(f"vectors: +{written} new (total {total})")
    out = graph_stage(series, GRAPHS_DIR)
    print(f"graph: {out}")
    demo = nearest_prices(conn, "RTX 5060 barata oferta")
    for hit in demo:
        print(
            f"nearest: {hit['sku']:<10} R${hit['amount_cents'] / 100:>10,.2f}"
            f"  {hit['source']:<10} {hit['day']} (d={hit['distance']:.3f})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
