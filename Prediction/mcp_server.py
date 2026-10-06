"""MCP server exposing the PromoDeals price pipeline as tools.

Server name: ``promodeals_mcp`` (stdio transport). Tools:

- ``promodeals_price_floors``: daily floors per SKU with deal verdicts
  against the fixed baselines (RTX 5060 <= R$2400, RTX 5090 <= R$22000;
  DDR5 learned from the median).
- ``promodeals_deal_alerts``: rows from the deal_alerts table.
- ``promodeals_nearest_prices``: KNN over the sqlite-vec price vectors.
- ``promodeals_harvest``: run a live WebSearch harvest into the database.

The database path comes from ``PROMODEALS_DB`` (default
``~/Swarm-Prediction/Prediction/offers.db``) so tests can point it at a
temporary database.

Run with either project venv (needs mcp, numpy, sqlite-vec):
    uv run --project ~/Swarm-Prediction python ~/Swarm-Prediction/Prediction/mcp_server.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, ConfigDict, Field

sys_path_parent = str(Path(__file__).resolve().parent.parent)
if sys_path_parent not in sys.path:
    sys.path.insert(0, sys_path_parent)  # noqa: E402 - Prediction package import below

from Prediction.br_hardware import PRODUCTS  # noqa: E402

mcp = MCPServer("promodeals_mcp")

DEFAULT_DB = Path(__file__).resolve().parent / "offers.db"
SEMANTIC_PATH = Path.home() / "Swarm" / "WebSearch" / "backend" / "semantic.py"
SKU_NAMES = {p.sku: p.name for p in PRODUCTS}
_BASELINES_FALLBACK: dict[str, float | None] = {
    "rtx-5060": 2400.0,
    "rtx-5090": 22000.0,
    "ddr5-16gb": None,
    "ddr5-32gb": None,
    "ddr5-64gb": None,
}


def db_path() -> Path:
    """Resolve the offers database path (``PROMODEALS_DB`` overrides)."""
    override = os.environ.get("PROMODEALS_DB", "").strip()
    return Path(override).expanduser() if override else DEFAULT_DB


def connect_db() -> sqlite3.Connection:
    """Open the offers database with row access by name."""
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    return conn


def load_baselines() -> dict[str, float | None]:
    """Deal baselines from the harvest module, with a static fallback."""
    try:
        from Prediction.harvest import BASELINES

        return dict(BASELINES)
    except ImportError:
        return dict(_BASELINES_FALLBACK)


def load_lexical_embedder(dim: int) -> Any:
    """Load the Swarm LexicalEmbedder by file path, bypassing package inits."""
    loader = SourceFileLoader("promodeals_semantic", str(SEMANTIC_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load embedder module from {SEMANTIC_PATH}")
    module = importlib.util.module_from_spec(spec)
    # Typing machinery resolves classes against sys.modules during exec.
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module.LexicalEmbedder(dim=dim)


def floors_core(conn: sqlite3.Connection) -> dict[str, Any]:
    """Daily floors per SKU plus a deal verdict against the baseline."""
    baselines = load_baselines()
    rows = conn.execute(
        """
        SELECT sku, market_date, payment, floor_cents, n, data_origin
        FROM daily_floors ORDER BY sku, market_date
        """
    ).fetchall()
    per_sku: dict[str, list[dict[str, Any]]] = {}
    latest: dict[str, float] = {}
    for row in rows:
        entry = {
            "date": row["market_date"],
            "payment": row["payment"],
            "floor_brl": int(row["floor_cents"]) / 100,
            "n": int(row["n"]),
            "data_origin": row["data_origin"],
        }
        per_sku.setdefault(row["sku"], []).append(entry)
        latest[row["sku"]] = int(row["floor_cents"]) / 100
    result = []
    for sku, days in per_sku.items():
        baseline = baselines.get(sku)
        floor = latest.get(sku)
        if baseline is None:
            prices = [d["floor_brl"] for d in days]
            median = sorted(prices)[len(prices) // 2] if prices else None
            verdict = (
                f"baseline learned: deal below R${0.7 * median:,.2f}"
                if median is not None
                else "no data"
            )
        elif floor is not None and floor <= baseline:
            verdict = f"DEAL (floor <= R${baseline:,.0f})"
        elif floor is not None and floor <= baseline + 400:
            verdict = "near baseline"
        else:
            verdict = f"not a deal (> R${baseline:,.0f})"
        result.append(
            {
                "sku": sku,
                "name": SKU_NAMES.get(sku, sku),
                "latest_floor_brl": floor,
                "baseline_brl": baseline,
                "verdict": verdict,
                "history_days": len(days),
            }
        )
    return {"db": str(db_path()), "skus": result}


def alerts_core(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Deal alerts: floor at or below 70% of the prior 30-day median."""
    rows = conn.execute(
        """
        SELECT sku, market_date, payment, floor_cents,
               baseline_median_cents, baseline_n
        FROM deal_alerts ORDER BY market_date, sku
        """
    ).fetchall()
    return [
        {
            "sku": row["sku"],
            "date": row["market_date"],
            "payment": row["payment"],
            "floor_brl": int(row["floor_cents"]) / 100,
            "baseline_median_brl": int(row["baseline_median_cents"]) / 100,
            "baseline_days": int(row["baseline_n"]),
        }
        for row in rows
    ]


def nearest_core(
    conn: sqlite3.Connection, query: str, k: int = 5, condition: str | None = None
) -> list[dict[str, Any]]:
    """K-nearest price observations for a natural-language query."""
    import sqlite_vec

    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
    except sqlite3.OperationalError:
        return []  # extension unavailable on this SQLite build
    embedder = load_lexical_embedder(1024)
    vector = embedder.embed([query])[0].astype("float32").tobytes()
    where = "WHERE embedding MATCH ? AND k = ?"
    params: list[Any] = [vector, k]
    if condition:
        where += " AND m.condition = ?"
        params.append(condition)
    try:
        rows = conn.execute(
            f"""
            SELECT m.sku, m.source, m.observed_on, m.condition, m.amount_cents, m.url,
                   distance
            FROM price_vectors v
            JOIN price_vector_meta m ON m.vec_rowid = v.rowid
            {where}
            ORDER BY distance
            """,
            params,
        ).fetchall()
    except sqlite3.OperationalError:
        return []  # vectors not built yet (run ingest.vector_stage)
    return [
        {
            "sku": row["sku"],
            "name": SKU_NAMES.get(row["sku"], row["sku"]),
            "source": row["source"],
            "date": row["observed_on"],
            "condition": row["condition"],
            "price_brl": int(row["amount_cents"]) / 100,
            "url": row["url"],
            "distance": round(float(row["distance"]), 4),
        }
        for row in rows
    ]


# --- input models -----------------------------------------------------------------


class FloorsInput(BaseModel):
    """Input model for the floors tool."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class AlertsInput(BaseModel):
    """Input model for the alerts tool."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class NearestInput(BaseModel):
    """Input model for the KNN price lookup."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: str = Field(
        ...,
        description="Natural-language price lookup, e.g. 'RTX 5060 barata' or 'DDR5 32GB kit'",
        min_length=2,
        max_length=200,
    )
    k: int = Field(default=5, description="Maximum results to return", ge=1, le=25)
    condition: str | None = Field(
        default=None, description="Filter by 'new' or 'used' (OLX); None = both"
    )


class HarvestInput(BaseModel):
    """Input model for the live harvest tool."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


# --- tools -------------------------------------------------------------------------


@mcp.tool(
    name="promodeals_price_floors",
    annotations={
        "title": "Daily BR price floors",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def promodeals_price_floors(params: FloorsInput) -> str:
    """Daily price floors per SKU with deal verdicts.

    Reads the daily_floors table built by the harvest pipeline and compares
    the latest floor against fixed baselines (RTX 5060 <= R$2400,
    RTX 5090 <= R$22000; DDR5 baselines are learned from the floor median).

    Returns:
        str: JSON ``{"db": str, "skus": [{"sku", "name", "latest_floor_brl",
        "baseline_brl", "verdict", "history_days"}]}``; empty ``skus`` when no
        harvest has run yet (then run promodeals_harvest first).
    """
    del params
    conn = connect_db()
    try:
        return json.dumps(floors_core(conn), indent=2, ensure_ascii=False)
    finally:
        conn.close()


@mcp.tool(
    name="promodeals_deal_alerts",
    annotations={
        "title": "Deal alerts",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def promodeals_deal_alerts(params: AlertsInput) -> str:
    """List deal alerts (floor at or below 70% of the prior 30-day median).

    Needs at least 5 prior days of floors per SKU; early databases return [].

    Returns:
        str: JSON array of ``{"sku", "date", "payment", "floor_brl",
        "baseline_median_brl", "baseline_days"}``.
    """
    del params
    conn = connect_db()
    try:
        return json.dumps(alerts_core(conn), indent=2, ensure_ascii=False)
    finally:
        conn.close()


@mcp.tool(
    name="promodeals_nearest_prices",
    annotations={
        "title": "Semantic price lookup",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def promodeals_nearest_prices(params: NearestInput) -> str:
    """K-nearest stored price observations for a natural-language query.

    Searches the sqlite-vec price vectors built from harvested observations
    (product name, source, date, price). Deterministic lexical embeddings.

    Returns:
        str: JSON array of ``{"sku", "name", "source", "date", "condition",
        "price_brl", "url", "distance"}``, best match first.
    """
    conn = connect_db()
    try:
        hits = nearest_core(conn, params.query, k=params.k, condition=params.condition)
    finally:
        conn.close()
    if not hits:
        return f"No observations indexed yet for '{params.query}' — run promodeals_harvest first."
    return json.dumps(hits, indent=2, ensure_ascii=False)


@mcp.tool(
    name="promodeals_harvest",
    annotations={
        "title": "Run live BR price harvest",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def promodeals_harvest(params: HarvestInput) -> str:
    """Run a live WebSearch harvest and rebuild floors/alerts.

    Queries ddglite + exa across the 11 BR sources, parses snippet prices,
    stores them as ``verification='snippet'`` observations (never treated as
    operator-verified), rebuilds daily floors and alerts. Network-bound:
    typically 1-4 minutes.

    Returns:
        str: JSON ``{"ok": true, "report": <harvest stdout lines>}`` or
        ``{"ok": false, "error": <message>}`` with a recovery suggestion.
    """
    del params
    import io
    from contextlib import redirect_stdout

    try:
        from Prediction import harvest as harvest_mod
    except ImportError as exc:
        return json.dumps({"ok": False, "error": f"harvest module unavailable: {exc}"})
    buffer = io.StringIO()
    try:
        with redirect_stdout(buffer):
            harvest_mod.main()
    except Exception as exc:  # noqa: BLE001 - surfaced verbatim to the caller
        return json.dumps(
            {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "hint": "check vault keys (EXA_API_KEY) and network, then retry",
            }
        )
    return json.dumps({"ok": True, "report": buffer.getvalue().splitlines()})


if __name__ == "__main__":
    mcp.run()
