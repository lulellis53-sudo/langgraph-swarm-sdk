"""Bounded live harvest for the BotDeal catalog: one dork query per SKU.

Unlike :mod:`Prediction.harvest` (per-source site-scoped queries), this driver
runs ONE discovery dork per SKU with a recent ``after:`` window, resolves each
hit to a catalog source via the URL host, stores snippet-price observations in
the offers SQLite store, and writes schema-valid product records into the
day-partitioned Parquet database (``Database/<Month>/DAY<d>/``). It then
rebuilds floors/alerts and prints a report with the ``FLOOR_TARGETS`` verdict.

Run from ~/BotDeal with the lane venv:

    PYTHONPATH="$HOME/BotDeal:$HOME/Swarm-Prediction" \\
      ~/Swarm-Prediction/.venv/bin/python -m Prediction.BotDeal.harvest_run \\
      --skus rtx-5090,ddr5-32gb --days 7
"""

from __future__ import annotations

import argparse
import datetime as dt
from typing import Any

from Prediction import harvest
from Prediction.BotDeal.database import append_products
from Prediction.BotDeal.discovery import product_dork
from Prediction.BotDeal.hardware import load_catalog, merged_floor_targets
from Prediction.br_hardware import (
    connect,
    floor_status,
    import_observation,
    market_today,
    rebuild_alerts,
    rebuild_floors,
)


def _record(
    sku: str,
    url: str,
    title: str,
    snippet: str,
    source: str,
    day: str,
    price_brl: float | None,
    query: str,
) -> dict[str, Any]:
    return {
        "unique_id": sku,
        "name": title[:200] or url,
        "source": source,
        "url": url,
        "observed_at": day,
        "price": price_brl,
        "currency": "BRL" if price_brl is not None else None,
        "condition": "used" if source == "olx" else "new",
        "snippet": snippet[:500] or None,
        "query": query,
        "confidence": None,
    }


def _harvest_sku(conn, catalog, sku: str, *, window_days: int, limit: int) -> list[dict[str, Any]]:
    """Run one dork for ``sku``, store observations, and return the records."""
    product = next(item for item in catalog.products if item.sku == sku)
    plausible = catalog.plausible.get(sku)
    if plausible is None:
        print(f"{sku}: no plausible range; skipped")
        return []
    low, high = plausible
    today = market_today()
    day = today.isoformat()
    dork_kwargs: dict[str, Any] = {}
    if window_days > 0:
        dork_kwargs = {
            "after": dt.date.today() - dt.timedelta(days=window_days),
            "before": dt.date.today(),
        }
    query = product_dork(product.terms[0], **dork_kwargs)
    try:
        leads = harvest.leads_for(query)
    except Exception as exc:
        print(f"{sku}: search failed {type(exc).__name__}: {exc}")
        return []
    records: list[dict[str, Any]] = []
    for url, title, snippet in leads[:limit]:
        source = harvest.source_for(url)
        if source is None:
            continue
        cents = next(
            (c for c in (harvest.parse_brl_cents(t) for t in (title, snippet)) if c is not None),
            None,
        )
        price_brl = cents / 100 if cents is not None else None
        in_range = cents is not None and low * 100 <= cents <= high * 100
        if in_range:
            try:
                import_observation(
                    conn,
                    sku=sku,
                    source=source,
                    url=url,
                    observed_on=day,
                    amount_cents=cents,
                    payment="card",
                    condition="used" if source == "olx" else "new",
                    data_origin="observed",
                    evidence=f"snippet-derived price from search hit: {title[:120]}",
                    verification="snippet",
                )
            except ValueError as exc:
                print(f"{sku}: observation skipped ({exc})")
                continue
        if in_range or cents is None:
            records.append(_record(sku, url, title, snippet, source, day, price_brl, query))
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skus", default="rtx-5090,ddr5-32gb", help="comma-separated SKUs")
    parser.add_argument("--days", type=int, default=7, help="after: window in days")
    parser.add_argument("--limit", type=int, default=10, help="max hits per SKU")
    parser.add_argument("--db", default="offers.db")
    args = parser.parse_args(argv)

    catalog = load_catalog()
    wanted = [sku.strip() for sku in args.skus.split(",") if sku.strip()]
    unknown = [sku for sku in wanted if sku not in catalog.skus]
    if unknown:
        raise SystemExit(f"unknown skus: {unknown}")

    targets = merged_floor_targets()
    conn = connect(args.db)
    try:
        all_records: list[dict[str, Any]] = []
        for sku in wanted:
            records = _harvest_sku(conn, catalog, sku, window_days=args.days, limit=args.limit)
            all_records.extend(records)
            print(f"{sku}: {len(records)} stored hits")
        floors = rebuild_floors(conn)
        alerts = rebuild_alerts(conn)
        for sku in wanted:
            row = conn.execute(
                "SELECT MIN(floor_cents) AS floor FROM daily_floors WHERE sku = ?", (sku,)
            ).fetchone()
            floor = row["floor"] if row and row["floor"] is not None else None
            if floor is not None:
                verdict = floor_status(sku, int(floor))
                print(f"floor {sku}: R${floor / 100:,.2f} -> {verdict}")
    finally:
        conn.close()

    if all_records:
        by_day: dict[str, list[dict[str, Any]]] = {}
        for record in all_records:
            observed = dt.date.fromisoformat(str(record["observed_at"]))
            by_day.setdefault(observed.isoformat(), []).append(record)
        for day, records in by_day.items():
            observed = dt.date.fromisoformat(day)
            month = observed.strftime("%B")
            for record in records:
                append_products([record], month=month, day=observed.day)
            print(f"parquet: {len(records)} rows -> Database/{month}/DAY{observed.day}/")

    for sku in wanted:
        if sku in targets:
            low, high = targets[sku]
            print(f"target {sku}: low-floor range R${low / 100:,.0f}–R${high / 100:,.0f}")
    print(f"floors={floors} alerts={alerts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
