"""One BotDeal run: search -> scrape -> observe -> floors -> alerts -> forecast.

This is the single per-run entry point for the three-worktree chain
(WebSearch -> BotDeal -> Prediction). It exists because the pieces were
previously only reachable through separate commands, so no run recorded what it
did and no run could be compared with the last one.

Each invocation is one row in ``runs``. A run is *idempotent*: the underlying
writers use ``INSERT OR IGNORE`` with UNIQUE constraints, so running twice on
the same market date does not double-count observations. A run is *resumable*
in the sense that a failed source only records an error and leaves earlier
observations intact.

The window reaches back ``--lookback-days`` days (default 7) rather than a
single day, so consecutive runs overlap and a SKU can accumulate the multi-day
floor series that :data:`Prediction.br_hardware.FORECAST_MIN_DAYS` requires.

Run from ~/BotDeal with the Prediction venv (the only one with lightgbm)::

    PYTHONPATH="$HOME/BotDeal:$HOME/BotDeal" \\
      ~/BotDeal/.venv/bin/python -m Prediction.BotDeal.run --lookback-days 7
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from typing import Any

from Prediction.BotDeal.hardware import load_catalog
from Prediction.BotDeal.pipeline import _PRICE, _scrape, _site_query, load_pipeline
from Prediction.br_hardware import (
    FORECAST_MIN_DAYS,
    connect,
    finish_run,
    forecastable_payments,
    import_observation,
    market_today,
    previous_run,
    rebuild_alerts,
    rebuild_floors,
    score_predictions,
    start_run,
)
from Prediction.harvest import parse_brl_cents

__all__ = ["RunReport", "run_once"]

#: Default lookback window in days. Must reach FORECAST_MIN_DAYS over
#: successive runs; a single-day window can never satisfy it.
DEFAULT_LOOKBACK_DAYS = 7


@dataclass
class RunReport:
    """What one run did, for the operator and for the runs table."""

    run_id: int = 0
    market_date: str = ""
    lookback_days: int = DEFAULT_LOOKBACK_DAYS
    queries: int = 0
    hits: int = 0
    observations: int = 0
    floors: int = 0
    alerts: int = 0
    forecasts_ready: int = 0
    forecasts_unavailable: int = 0
    errors: list[str] = field(default_factory=list)
    prices: dict[str, dict[str, float]] = field(default_factory=dict)
    scored: int = 0
    mape: float = 0.0
    detail: str = ""
    previous: dict[str, int | None] = field(default_factory=dict)

    @property
    def status(self) -> str:
        """``ok`` when nothing failed, ``partial`` for some errors, ``failed`` for none usable."""
        if not self.errors:
            return "ok"
        return "partial" if (self.observations or self.hits) else "failed"

    def counters(self) -> dict[str, int]:
        """Column values for the ``runs`` row."""
        return {
            "queries": self.queries,
            "hits": self.hits,
            "observations": self.observations,
            "floors": self.floors,
            "alerts": self.alerts,
            "forecasts_ready": self.forecasts_ready,
            "forecasts_unavailable": self.forecasts_unavailable,
            "errors": len(self.errors),
        }


def _delta(current: int, previous: int | None) -> str:
    """Render a counter against the previous run, e.g. ``12 (+3)``."""
    if previous is None:
        return str(current)
    diff = current - previous
    if diff == 0:
        return f"{current} (=)"
    return f"{current} ({'+' if diff > 0 else ''}{diff})"


def run_once(
    *,
    db: str = "offers.db",
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    skus: list[str] | None = None,
    limit: int = 10,
    horizon: int = 7,
    scrape_top: int = 3,
    dry_run: bool = False,
    seed: dict[str, float] | None = None,
) -> RunReport:
    """Execute one full run and return its report.

    Args:
        db: Offer database path.
        lookback_days: Search window length; overlapping windows accumulate history.
        skus: SKUs to cover; ``None`` uses every catalog SKU.
        limit: Maximum hits per query.
        horizon: Forecast horizon in days.
        scrape_top: Pages to scrape per SKU (prices live on pages, not snippets).
        dry_run: Build queries and report them without searching or writing.
        seed: Test seam mapping sku to a centavos price, bypassing the network.

    Returns:
        The populated :class:`RunReport`.
    """
    config = load_pipeline()
    catalog = load_catalog()
    report = RunReport(lookback_days=lookback_days)
    today = market_today()
    report.market_date = today.isoformat()
    prompt = str(config.get("prompt", "{model} preço oferta"))
    aliases: dict[str, list[str]] = config.get("aliases", {}) or {}
    wanted = skus or [p.sku for p in catalog.products]

    # --- dry run: show the queries a real run would issue ---------------
    if dry_run:
        for sku in wanted:
            product = next((p for p in catalog.products if p.sku == sku), None)
            if product is None:
                report.errors.append(f"unknown sku: {sku}")
                continue
            for source in catalog.sources:
                if source.kind == "social":
                    continue
                report.queries += 1
                print(
                    _site_query(
                        list(product.terms),
                        prompt=prompt,
                        site=source.domain,
                        window_days=lookback_days,
                        aliases=aliases,
                    )
                )
        report.detail = "dry-run: no search, no writes"
        return report

    conn = connect(db)
    try:
        report.run_id = start_run(
            conn,
            market_date=report.market_date,
            lookback_days=lookback_days,
            skus=wanted,
        )
        prev = previous_run(conn, report.run_id)

        # Test seam: a supplied price seed stands in for live search results.
        if seed is not None:
            for sku, price_cents_value in seed.items():
                source = catalog.sources[0]
                import_observation(
                    conn,
                    sku=sku,
                    source=source.name,
                    url=f"https://{source.domain}/seed/{sku}/{today.isoformat()}",
                    observed_on=today.isoformat(),
                    amount_cents=int(price_cents_value),
                    payment="card",
                    condition="new",
                    data_origin="observed",
                    evidence="seeded run (test seam)",
                    verification="snippet",
                )
                report.observations += 1
            report.detail = "seeded run"
        else:
            from WebSearch.agent_tools import search_hits

            for sku in wanted:
                product = next((p for p in catalog.products if p.sku == sku), None)
                if product is None:
                    report.errors.append(f"unknown sku: {sku}")
                    continue
                plausible = catalog.plausible.get(sku)
                prices: list[float] = []
                scraped = 0
                for source in catalog.sources:
                    if source.kind == "social":
                        continue
                    query = _site_query(
                        list(product.terms),
                        prompt=prompt,
                        site=source.domain,
                        window_days=lookback_days,
                        aliases=aliases,
                    )
                    report.queries += 1
                    try:
                        hits = search_hits(query, limit=limit)
                    except Exception as exc:  # one dead provider must not kill the run
                        report.errors.append(f"{sku}/{source.name}: {type(exc).__name__}: {exc}")
                        continue
                    for hit in hits[:limit]:
                        report.hits += 1
                        # Prices live on the page, so scrape then fall back to
                        # the snippet. The scrape goes through the lane's own
                        # fetch path so politeness/robots/caps apply.
                        cents = None
                        if scraped < scrape_top:
                            text = _scrape(hit.url, timeout_s=15)
                            if text:
                                scraped += 1
                                match = _PRICE.search(text)
                                if match:
                                    cents = parse_brl_cents(match.group(0))
                        if cents is None:
                            cents = next(
                                (
                                    c
                                    for c in (parse_brl_cents(t) for t in (hit.title, hit.snippet))
                                    if c is not None
                                ),
                                None,
                            )
                        if cents is None or not plausible:
                            continue
                        if not plausible[0] * 100 <= cents <= plausible[1] * 100:
                            continue
                        try:
                            import_observation(
                                conn,
                                sku=sku,
                                source=source.name,
                                url=hit.url,
                                observed_on=today.isoformat(),
                                amount_cents=cents,
                                payment="card",
                                condition="used" if source.name == "olx" else "new",
                                data_origin="observed",
                                evidence=f"run {report.run_id}: {hit.title[:120]}",
                                verification="snippet",
                            )
                        except ValueError as exc:
                            report.errors.append(f"{sku}/{source.name}: {exc}")
                            continue
                        report.observations += 1
                        prices.append(cents / 100)
                if prices:
                    report.prices[sku] = {
                        "min": min(prices),
                        "avg": round(sum(prices) / len(prices), 2),
                        "max": max(prices),
                        "n": len(prices),
                    }

        # --- derive floors, alerts, forecasts --------------------------
        report.floors = rebuild_floors(conn)
        report.alerts = rebuild_alerts(conn)

        for sku in wanted:
            payments = forecastable_payments(conn, sku) or ["card"]
            payment = payments[0]
            status = write_forecast_safely(
                conn, sku, horizon=horizon, payment=payment, run_id=report.run_id
            )
            if status == "ready":
                report.forecasts_ready += 1
            else:
                report.forecasts_unavailable += 1

        scores = score_predictions(conn, report.run_id)
        report.scored = scores["scored"]
        report.mape = float(scores["mape"])

        finish_run(
            conn,
            report.run_id,
            status=report.status,
            counters=report.counters(),
            detail=report.detail or f"{len(report.errors)} error(s)",
        )
        report.previous = {
            "queries": None if prev is None else int(prev["queries"]),
            "hits": None if prev is None else int(prev["hits"]),
            "observations": None if prev is None else int(prev["observations"]),
        }
    finally:
        conn.close()
    return report


def write_forecast_safely(
    conn: Any,
    sku: str,
    *,
    horizon: int,
    payment: str,
    run_id: int,
) -> str:
    """Call :func:`write_forecast` with the run's payment series.

    Kept separate so the engine import stays lazy and a missing lightgbm
    records ``unavailable`` instead of aborting the whole run.
    """
    from Prediction.br_hardware import _live_engine, write_forecast

    return write_forecast(
        conn,
        sku,
        engine=_live_engine(),
        horizon=horizon,
        payment=payment,
        run_id=run_id,
    )


def print_report(report: RunReport) -> None:
    """Print the run summary and the delta against the previous run."""
    prev = report.previous
    print(f"=== run {report.run_id} · {report.market_date} · lookback {report.lookback_days}d ===")
    print(f"  status              : {report.status}")
    print(f"  queries             : {_delta(report.queries, prev.get('queries'))}")
    print(f"  hits                : {_delta(report.hits, prev.get('hits'))}")
    print(f"  observations        : {_delta(report.observations, prev.get('observations'))}")
    print(f"  floors / alerts     : {report.floors} / {report.alerts}")
    print(
        f"  forecasts           : {report.forecasts_ready} ready, "
        f"{report.forecasts_unavailable} unavailable"
        f" (needs {FORECAST_MIN_DAYS} observed floors per sku/payment)"
    )
    if report.scored:
        print(f"  scored vs actual    : {report.scored} forecasts, MAPE {report.mape}%")
    else:
        print("  scored vs actual    : nothing scoreable yet")
    for sku, stats in sorted(report.prices.items()):
        print(
            f"  {sku:<18}: min R${stats['min']:,.2f} | avg R${stats['avg']:,.2f} "
            f"| max R${stats['max']:,.2f} (n={int(stats['n'])})"
        )
    if report.errors:
        print(f"  errors ({len(report.errors)}):")
        for line in report.errors[:10]:
            print(f"    - {line}")
        if len(report.errors) > 10:
            print(f"    … {len(report.errors) - 10} more")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for one run."""
    parser = argparse.ArgumentParser(description="One BotDeal run (search -> forecast)")
    parser.add_argument("--db", default="offers.db")
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--sku", action="append", dest="skus", default=None)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--horizon", type=int, default=7)
    parser.add_argument("--scrape-top", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true", help="print queries, do not search")
    parser.add_argument("--json", action="store_true", help="emit the report as JSON")
    args = parser.parse_args(argv)

    started = time.time()
    report = run_once(
        db=args.db,
        lookback_days=args.lookback_days,
        skus=args.skus,
        limit=args.limit,
        horizon=args.horizon,
        scrape_top=args.scrape_top,
        dry_run=args.dry_run,
    )
    if args.json:
        print(json.dumps(report.__dict__, indent=2, default=str))
    else:
        print_report(report)
        print(f"  elapsed             : {time.time() - started:.1f}s", file=sys.stderr)
    return 0 if report.status != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
