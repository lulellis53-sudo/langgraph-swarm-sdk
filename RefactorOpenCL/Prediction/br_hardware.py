"""Brazilian RTX 5000+ and DDR5 offer digestion.

Search queries are discovery leads. A snippet is never a verified price.
Daily floors, deal alerts, and forecasts use verified observations only.
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

MARKET_TZ = ZoneInfo("America/Sao_Paulo")
ALERT_RATIO = 0.70
ALERT_MIN_DAYS = 5
FORECAST_MIN_DAYS = 14

_SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    sku TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sources (
    name TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    kind TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS search_runs (
    id INTEGER PRIMARY KEY,
    sku TEXT NOT NULL,
    source TEXT NOT NULL,
    query TEXT NOT NULL,
    ran_at REAL NOT NULL,
    lead_count INTEGER NOT NULL,
    error TEXT
);
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY,
    sku TEXT NOT NULL,
    source TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    snippet TEXT NOT NULL,
    seen_at REAL NOT NULL,
    UNIQUE (sku, url)
);
CREATE TABLE IF NOT EXISTS price_observations (
    id INTEGER PRIMARY KEY,
    sku TEXT NOT NULL,
    source TEXT NOT NULL,
    url TEXT NOT NULL,
    observed_on TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    currency TEXT NOT NULL,
    payment TEXT NOT NULL,
    condition TEXT NOT NULL,
    verification TEXT NOT NULL,
    data_origin TEXT NOT NULL,
    evidence TEXT NOT NULL,
    UNIQUE (sku, url, observed_on, payment, amount_cents, data_origin)
);
CREATE TABLE IF NOT EXISTS daily_floors (
    sku TEXT NOT NULL,
    market_date TEXT NOT NULL,
    payment TEXT NOT NULL,
    floor_cents INTEGER NOT NULL,
    n INTEGER NOT NULL,
    data_origin TEXT NOT NULL,
    PRIMARY KEY (sku, market_date, payment, data_origin)
);
CREATE TABLE IF NOT EXISTS deal_alerts (
    sku TEXT NOT NULL,
    market_date TEXT NOT NULL,
    payment TEXT NOT NULL,
    floor_cents INTEGER NOT NULL,
    baseline_median_cents REAL NOT NULL,
    baseline_n INTEGER NOT NULL,
    PRIMARY KEY (sku, market_date, payment)
);
CREATE TABLE IF NOT EXISTS predictions (
    sku TEXT NOT NULL,
    horizon INTEGER NOT NULL,
    cutoff TEXT NOT NULL,
    point_cents INTEGER,
    status TEXT NOT NULL,
    detail TEXT NOT NULL,
    PRIMARY KEY (sku, horizon, cutoff)
);
"""


@dataclass(frozen=True, slots=True)
class Product:
    """One canonical hardware product."""

    sku: str
    name: str
    category: str
    terms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Source:
    """A Brazilian discovery site. The pipeline searches it; it does not crawl it."""

    name: str
    domain: str
    kind: str


@dataclass(frozen=True, slots=True)
class Lead:
    """One search hit. It is not a price observation."""

    url: str
    title: str
    snippet: str


class ForecastModel(Protocol):
    """Narrow fit/predict surface used by :func:`write_forecast`."""

    def fit(self, frame: object) -> object:
        """Fit on a long frame with ``unique_id``, ``ds``, and ``y``."""

    def predict(self, horizon: int) -> object:
        """Return a frame whose ``lgbm`` column is the point forecast."""


PRODUCTS: tuple[Product, ...] = (
    Product("rtx-5090", "NVIDIA GeForce RTX 5090", "gpu", ("RTX 5090",)),
    Product("rtx-5080", "NVIDIA GeForce RTX 5080", "gpu", ("RTX 5080",)),
    Product("rtx-5070-ti", "NVIDIA GeForce RTX 5070 Ti", "gpu", ("RTX 5070 Ti",)),
    Product("rtx-5070", "NVIDIA GeForce RTX 5070", "gpu", ("RTX 5070",)),
    Product("rtx-5060", "NVIDIA GeForce RTX 5060", "gpu", ("RTX 5060",)),
    Product("rtx-5060-ti", "NVIDIA GeForce RTX 5060 Ti", "gpu", ("RTX 5060 Ti",)),
    Product("rtx-5000-ada", "NVIDIA RTX 5000 Ada", "gpu", ("RTX 5000 Ada",)),
    Product("ryzen-5-9600x", "AMD Ryzen 5 9600X", "cpu", ("Ryzen 5 9600X",)),
    Product("ryzen-7-9700x", "AMD Ryzen 7 9700X", "cpu", ("Ryzen 7 9700X",)),
    Product("ryzen-7-9800x", "AMD Ryzen 7 9800X", "cpu", ("Ryzen 7 9800X",)),
    Product("ryzen-9-9900x", "AMD Ryzen 9 9900X", "cpu", ("Ryzen 9 9900X",)),
    Product("ryzen-9-9950x", "AMD Ryzen 9 9950X", "cpu", ("Ryzen 9 9950X",)),
    Product("ryzen-7-9800x3d", "AMD Ryzen 7 9800X3D", "cpu", ("Ryzen 7 9800X3D",)),
    Product("ryzen-7-9850x3d", "AMD Ryzen 7 9850X3D", "cpu", ("Ryzen 7 9850X3D",)),
    Product("ryzen-9-9950x3d", "AMD Ryzen 9 9950X3D", "cpu", ("Ryzen 9 9950X3D",)),
    Product("ryzen-9-9950x3d2", "AMD Ryzen 9 9950X3D2", "cpu", ("Ryzen 9 9950X3D2",)),
    Product("ddr5-1x8gb", "DDR5 1x8GB", "memory", ("DDR5 8GB", "memoria ddr5 8gb")),
    Product("ddr5-2x8gb", "DDR5 2x8GB", "memory", ("DDR5 2x8GB", "kit ddr5 16gb")),
    Product("ddr5-1x16gb", "DDR5 1x16GB", "memory", ("DDR5 16GB", "memoria ddr5 16gb")),
    Product("ddr5-2x16gb", "DDR5 2x16GB", "memory", ("DDR5 2x16GB", "kit ddr5 32gb")),
    Product("ddr5-1x32gb", "DDR5 1x32GB", "memory", ("DDR5 32GB", "memoria ddr5 32gb")),
    Product("ddr5-2x32gb", "DDR5 2x32GB", "memory", ("DDR5 2x32GB", "kit ddr5 64gb")),
    Product("ddr5-1x64gb", "DDR5 1x64GB", "memory", ("DDR5 64GB", "memoria ddr5 64gb")),
)

#: User-supplied low-floor ranges in BRL centavos: a floor at or below the
#: range top counts as a good deal, at or below the bottom as exceptional.
FLOOR_TARGETS: dict[str, tuple[int, int]] = {
    "rtx-5090": (1_800_000, 1_900_000),  # R$18.000–R$19.000
}
SOURCES: tuple[Source, ...] = (
    Source("kabum", "kabum.com.br", "retailer"),
    Source("terabyte", "terabyteshop.com.br", "retailer"),
    Source("magalu", "magazineluiza.com.br", "retailer"),
    Source("pichau", "pichau.com.br", "retailer"),
    Source("amazon-br", "amazon.com.br", "retailer"),
    Source("mercadolivre", "mercadolivre.com.br", "marketplace"),
    Source("casasbahia", "casasbahia.com.br", "retailer"),
    Source("x", "x.com", "social"),
    Source("telegram", "t.me", "social"),
    Source("olx", "olx.com.br", "marketplace"),
    Source("promobit", "promobit.com.br", "community"),
    Source("pelando", "pelando.com.br", "community"),
)
_PAYMENTS = frozenset({"pix", "card"})
_CONDITIONS = frozenset({"new", "used"})
_ORIGINS = frozenset({"observed", "synthetic"})
_VERIFICATIONS = frozenset({"verified", "snippet"})


def floor_status(sku: str, floor_cents: int) -> str:
    """Classify an observed floor against ``FLOOR_TARGETS``.

    Returns ``"exceptional"`` (at or below the range bottom), ``"low"`` (at or
    below the range top), ``"above"`` (inside or above the range), or
    ``"no_target"`` for SKUs without a user-supplied range.
    """
    target = FLOOR_TARGETS.get(sku)
    if target is None:
        return "no_target"
    low, high = target
    if floor_cents <= low:
        return "exceptional"
    if floor_cents <= high:
        return "low"
    return "above"


def market_today(at: float | None = None) -> date:
    """Return the calendar date in America/Sao_Paulo.

    Args:
        at: Unix timestamp. ``None`` uses the current time.
    """
    moment = datetime.fromtimestamp(time.time() if at is None else at, MARKET_TZ)
    return moment.date()


def connect(path: str | Path) -> sqlite3.Connection:
    """Open the offer database and create tables.

    Args:
        path: SQLite path, or ``:memory:``.
    """
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def seed_catalog(conn: sqlite3.Connection) -> None:
    """Insert the RTX 5000+ and DDR5 catalog and the Brazilian sources."""
    conn.executemany(
        "INSERT OR IGNORE INTO products(sku, name, category) VALUES (?, ?, ?)",
        [(item.sku, item.name, item.category) for item in PRODUCTS],
    )
    conn.executemany(
        "INSERT OR IGNORE INTO sources(name, domain, kind) VALUES (?, ?, ?)",
        [(item.name, item.domain, item.kind) for item in SOURCES],
    )
    conn.commit()


def build_queries(
    product: Product,
    source: Source,
    *,
    on: date,
) -> tuple[str, str]:
    """Return the broad query and the coupon query for one product and site.

    ``before`` is the next calendar day, so the window is ``on``.

    Args:
        product: Catalog product.
        source: Discovery site.
        on: Market date used as the ``after:`` bound.
    """
    product_clause = " OR ".join(f'"{term}"' for term in product.terms)
    window = f"after:{on.isoformat()} before:{(on + timedelta(days=1)).isoformat()}"
    site = f"site:{source.domain}"
    broad = f"({product_clause}) (preco OR oferta) {site} {window}"
    coupon = f"({product_clause}) (cupom OR codigo OR promo OR desconto) {site} {window}"
    return broad, coupon


def import_observation(
    conn: sqlite3.Connection,
    *,
    sku: str,
    source: str,
    url: str,
    observed_on: str,
    amount_cents: int,
    payment: str,
    condition: str,
    data_origin: str,
    evidence: str,
    verification: str = "verified",
) -> None:
    """Store one price observation. Repeating the same row is a no-op.

    Args:
        conn: Open offer database.
        sku: Catalog product sku.
        source: Source name.
        url: Evidence page.
        observed_on: Market date, ``YYYY-MM-DD``.
        amount_cents: Price in centavos. Must be positive.
        payment: ``pix`` or ``card``.
        condition: ``new`` or ``used``.
        data_origin: ``observed`` or ``synthetic``.
        evidence: Note or URL that justifies the verification.
        verification: ``verified`` (operator-confirmed) or ``snippet`` (price
            parsed from a search-result snippet; observed but unconfirmed).

    Raises:
        ValueError: When a field is missing or not in the allowed set.
    """
    if sku not in {item.sku for item in PRODUCTS}:
        raise ValueError(f"unknown sku: {sku}")
    if source not in {item.name for item in SOURCES}:
        raise ValueError(f"unknown source: {source}")
    if not url.strip() or not evidence.strip():
        raise ValueError("url and evidence are required")
    date.fromisoformat(observed_on)
    if amount_cents <= 0:
        raise ValueError("amount_cents must be positive")
    if payment not in _PAYMENTS or condition not in _CONDITIONS or data_origin not in _ORIGINS:
        raise ValueError("payment, condition, or data_origin is not allowed")
    if verification not in _VERIFICATIONS:
        raise ValueError("verification is not allowed")
    conn.execute(
        """
        INSERT OR IGNORE INTO price_observations(
            sku, source, url, observed_on, amount_cents, currency, payment,
            condition, verification, data_origin, evidence
        ) VALUES (?, ?, ?, ?, ?, 'BRL', ?, ?, ?, ?, ?)
        """,
        (
            sku,
            source,
            url,
            observed_on,
            amount_cents,
            payment,
            condition,
            verification,
            data_origin,
            evidence,
        ),
    )
    conn.commit()


def run_digest(
    conn: sqlite3.Connection,
    search: Callable[[str], Sequence[Lead]],
    *,
    on: date | None = None,
    at: float | None = None,
) -> dict[str, int]:
    """Search every product and source, and store hits as leads.

    A search error is stored on the run row and does not remove older leads.

    Args:
        conn: Open offer database.
        search: Maps one query to leads. Tests pass a fake. Live runs pass
            :func:`websearch_leads`.
        on: Market date for the query window.
        at: Timestamp stored on the run and the leads.

    Returns:
        Counts of queries, stored leads, and failed queries.
    """
    seed_catalog(conn)
    day = market_today(at) if on is None else on
    stamp = time.time() if at is None else at
    queries = 0
    stored = 0
    failed = 0
    for product in PRODUCTS:
        for source in SOURCES:
            for query in build_queries(product, source, on=day):
                queries += 1
                try:
                    leads = list(search(query))
                except Exception as exc:
                    failed += 1
                    conn.execute(
                        """
                        INSERT INTO search_runs(sku, source, query, ran_at, lead_count, error)
                        VALUES (?, ?, ?, ?, 0, ?)
                        """,
                        (product.sku, source.name, query, stamp, f"{type(exc).__name__}: {exc}"),
                    )
                    continue
                conn.execute(
                    """
                    INSERT INTO search_runs(sku, source, query, ran_at, lead_count, error)
                    VALUES (?, ?, ?, ?, ?, NULL)
                    """,
                    (product.sku, source.name, query, stamp, len(leads)),
                )
                for lead in leads:
                    cursor = conn.execute(
                        """
                        INSERT OR IGNORE INTO leads(sku, source, url, title, snippet, seen_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (product.sku, source.name, lead.url, lead.title, lead.snippet, stamp),
                    )
                    stored += cursor.rowcount
    conn.commit()
    return {"queries": queries, "stored": stored, "failed": failed}


def websearch_leads(query: str) -> list[Lead]:
    """Run one query through the WebSearch lane.

    Args:
        query: Broad or coupon query from :func:`build_queries`.

    Returns:
        Leads with url, title, and snippet.

    Raises:
        ImportError: When the WebSearch package is not importable.
    """
    from WebSearch.agent_tools import search_hits

    hits = search_hits(query)
    return [Lead(url=hit.url, title=hit.title, snippet=hit.snippet) for hit in hits]


def rebuild_floors(conn: sqlite3.Connection) -> int:
    """Recompute daily floors from new-condition prices.

    Pix and card stay separate. Used goods are excluded. Snippet-derived
    prices (unconfirmed) count alongside operator-verified ones; each origin
    is its own floor so synthetic rows cannot lower an observed floor.

    Args:
        conn: Open offer database.

    Returns:
        Number of floor rows written.
    """
    conn.execute("DELETE FROM daily_floors")
    rows = conn.execute(
        """
        SELECT sku, observed_on, payment, data_origin, MIN(amount_cents), COUNT(*)
        FROM price_observations
        WHERE verification IN ('verified', 'snippet') AND condition = 'new'
        GROUP BY sku, observed_on, payment, data_origin
        """
    ).fetchall()
    conn.executemany(
        """
        INSERT INTO daily_floors(sku, market_date, payment, floor_cents, n, data_origin)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [(row[0], row[1], row[2], int(row[4]), int(row[5]), row[3]) for row in rows],
    )
    conn.commit()
    return len(rows)


def rebuild_alerts(conn: sqlite3.Connection) -> int:
    """Alert when an observed floor is at or below 70% of the prior median.

    The baseline is the previous 30 calendar days, excluding the alert day,
    and needs at least five floors. Synthetic floors never alert.

    Args:
        conn: Open offer database. Floors must already be rebuilt.

    Returns:
        Number of alert rows written.
    """
    conn.execute("DELETE FROM deal_alerts")
    floors = conn.execute(
        """
        SELECT sku, market_date, payment, floor_cents
        FROM daily_floors
        WHERE data_origin = 'observed'
        ORDER BY sku, payment, market_date
        """
    ).fetchall()
    written = 0
    for floor in floors:
        start = date.fromisoformat(floor["market_date"]) - timedelta(days=30)
        prior = conn.execute(
            """
            SELECT floor_cents FROM daily_floors
            WHERE sku = ? AND payment = ? AND data_origin = 'observed'
              AND market_date >= ? AND market_date < ?
            """,
            (floor["sku"], floor["payment"], start.isoformat(), floor["market_date"]),
        ).fetchall()
        if len(prior) < ALERT_MIN_DAYS:
            continue
        median = statistics.median(int(row["floor_cents"]) for row in prior)
        if int(floor["floor_cents"]) <= ALERT_RATIO * median:
            conn.execute(
                """
                INSERT INTO deal_alerts(
                    sku, market_date, payment, floor_cents, baseline_median_cents, baseline_n
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    floor["sku"],
                    floor["market_date"],
                    floor["payment"],
                    int(floor["floor_cents"]),
                    median,
                    len(prior),
                ),
            )
            written += 1
    conn.commit()
    return written


def write_forecast(
    conn: sqlite3.Connection,
    sku: str,
    *,
    engine: ForecastModel | None,
    horizon: int = 7,
    cutoff: str | None = None,
) -> str:
    """Forecast one observed price floor, or record that the history is too short.

    Args:
        conn: Open offer database.
        sku: Catalog product sku.
        engine: Fitted by this function. ``None`` records an unavailable forecast.
        horizon: Days ahead. Must be positive.
        cutoff: Last market date allowed into the series. ``None`` uses the latest floor.

    Returns:
        ``ready`` or ``unavailable``.

    Raises:
        ValueError: When ``horizon`` is below 1 or ``sku`` is unknown.
    """
    if horizon < 1:
        raise ValueError("horizon must be at least 1")
    if sku not in {item.sku for item in PRODUCTS}:
        raise ValueError(f"unknown sku: {sku}")
    rows = conn.execute(
        """
        SELECT market_date, floor_cents FROM daily_floors
        WHERE sku = ? AND payment = 'pix' AND data_origin = 'observed'
        ORDER BY market_date
        """,
        (sku,),
    ).fetchall()
    if cutoff is not None:
        rows = [row for row in rows if row["market_date"] <= cutoff]
    last = cutoff or (rows[-1]["market_date"] if rows else market_today().isoformat())
    if engine is None or len(rows) < FORECAST_MIN_DAYS:
        detail = "need 14 observed pix floors" if engine is not None else "no forecast engine"
        _save_prediction(conn, sku, horizon, last, None, "unavailable", detail)
        return "unavailable"
    import pandas as pd

    frame = pd.DataFrame(
        {
            "unique_id": sku,
            "ds": pd.to_datetime([row["market_date"] for row in rows]),
            "y": [int(row["floor_cents"]) for row in rows],
        }
    )
    engine.fit(frame)
    predicted = engine.predict(horizon)
    point = int(round(float(predicted["lgbm"].iloc[0])))
    _save_prediction(conn, sku, horizon, last, point, "ready", "lgbm")
    return "ready"


def _save_prediction(
    conn: sqlite3.Connection,
    sku: str,
    horizon: int,
    cutoff: str,
    point_cents: int | None,
    status: str,
    detail: str,
) -> None:
    """Replace the prediction row for one sku, horizon, and cutoff."""
    conn.execute(
        """
        INSERT INTO predictions(sku, horizon, cutoff, point_cents, status, detail)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(sku, horizon, cutoff) DO UPDATE SET
            point_cents = excluded.point_cents,
            status = excluded.status,
            detail = excluded.detail
        """,
        (sku, horizon, cutoff, point_cents, status, detail),
    )
    conn.commit()


def _live_engine() -> ForecastModel | None:
    """Return the project forecast engine, or ``None`` when it is not installed."""
    try:
        from Prediction import ForecastEngine
    except ImportError:
        return None
    return ForecastEngine()


def _print_queries() -> None:
    """Print today's broad and coupon queries. This makes no network call."""
    day = market_today()
    for product in PRODUCTS:
        for source in SOURCES:
            broad, coupon = build_queries(product, source, on=day)
            print(broad)
            print(coupon)


def main(argv: list[str] | None = None) -> None:
    """Run catalog init, query printing, floors, or a forecast.

    Args:
        argv: CLI arguments. ``None`` reads the process arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="predictions_br.sqlite")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("queries")
    sub.add_parser("floors")
    forecast = sub.add_parser("forecast")
    forecast.add_argument("--sku", required=True)
    forecast.add_argument("--horizon", type=int, default=7)
    args = parser.parse_args(argv)
    if args.command == "queries":
        _print_queries()
        return
    conn = connect(args.db)
    try:
        if args.command == "init":
            seed_catalog(conn)
        elif args.command == "floors":
            floors = rebuild_floors(conn)
            alerts = rebuild_alerts(conn)
            print(f"floors={floors} alerts={alerts}")
        else:
            status = write_forecast(
                conn,
                args.sku,
                engine=_live_engine(),
                horizon=args.horizon,
            )
            print(status)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
