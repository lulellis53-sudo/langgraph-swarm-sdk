"""Run the prediction CLI with ``python -m technews.prediction``."""

import argparse
import sys
from pathlib import Path

from technews.prediction.features import build_frame
from technews.prediction.forecast import TrendForecaster
from technews.prediction.store import FeatureStore


def _cmd_backfill(args: argparse.Namespace) -> int:
    articles = Path(args.articles)
    if not articles.exists():
        print(f"articles db not found: {articles}", file=sys.stderr)
        return 1
    with FeatureStore(args.db) as store:
        rows = store.backfill_from_articles(articles)
    print(f"backfilled {rows} daily stat rows into {args.db}")
    return 0


def _cmd_forecast(args: argparse.Namespace) -> int:
    with FeatureStore(args.db) as store:
        counts = store.daily_counts()
        frame = build_frame(counts)
        forecaster = TrendForecaster(horizon=args.horizon)
        forecaster.fit(frame)
        points = forecaster.predict()
    if not points:
        print("no forecast-ready series in feature store", file=sys.stderr)
        return 1
    print(f"{'category':<20} {'date':<12} yhat")
    for point in points:
        print(f"{point.category:<20} {point.date:<12} {point.yhat:.2f}")
    return 0


def _cmd_movers(args: argparse.Namespace) -> int:
    with FeatureStore(args.db) as store:
        counts = store.daily_counts()
        frame = build_frame(counts)
        forecaster = TrendForecaster()
        forecaster.fit(frame)
        ranked = forecaster.movers(frame)
    if not ranked:
        print("no movers (insufficient or zero history)", file=sys.stderr)
        return 1
    print(f"{'category':<20} expected change")
    for category, change in ranked:
        print(f"{category:<20} {change:+.1%}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Return the prediction CLI parser."""
    parser = argparse.ArgumentParser(prog="technews.prediction", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_backfill = sub.add_parser("backfill", help="recompute daily stats from the articles DB")
    p_backfill.add_argument("--db", required=True, help="path to the feature store SQLite DB")
    p_backfill.add_argument(
        "--articles", required=True, help="path to the source articles SQLite DB"
    )
    p_backfill.set_defaults(func=_cmd_backfill)

    p_forecast = sub.add_parser("forecast", help="forecast daily counts per category")
    p_forecast.add_argument("--db", required=True, help="path to the feature store SQLite DB")
    p_forecast.add_argument("--horizon", type=int, default=7, help="days to forecast (default 7)")
    p_forecast.set_defaults(func=_cmd_forecast)

    p_movers = sub.add_parser("movers", help="rank categories by expected change")
    p_movers.add_argument("--db", required=True, help="path to the feature store SQLite DB")
    p_movers.set_defaults(func=_cmd_movers)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point; returns process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (ValueError, RuntimeError, OSError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
