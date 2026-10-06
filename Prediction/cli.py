"""CLI for the generic mlforecast engine (CSV in, metrics or forecasts out).

Usage::

    uv run --extra forecast python -m Prediction.cli backtest series.csv --horizon 7
    uv run --extra forecast python -m Prediction.cli predict series.csv --horizon 14
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
from Prediction.engine import ForecastConfig, ForecastEngine, ForecastError


def _load_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise ForecastError(f"input file not found: {path}")
    frame = pd.read_csv(path)
    if "ds" in frame.columns:
        frame["ds"] = pd.to_datetime(frame["ds"])
    return frame


def _cmd_backtest(args: argparse.Namespace) -> int:
    engine = ForecastEngine(
        ForecastConfig(
            freq=args.freq,
            lags=tuple(args.lags),
            step_size=args.step_size,
        )
    )
    metrics = engine.backtest(
        _load_csv(Path(args.input)),
        horizon=args.horizon,
        n_windows=args.windows,
        step_size=args.step_size,
    )
    if args.json:
        print(json.dumps(metrics.to_dict(orient="records"), indent=2))
    else:
        print(metrics.to_string(index=False))
    return 0


def _cmd_predict(args: argparse.Namespace) -> int:
    engine = ForecastEngine(
        ForecastConfig(freq=args.freq, lags=tuple(args.lags)),
    ).fit(_load_csv(Path(args.input)))
    forecast = engine.predict(args.horizon)
    out = Path(args.output) if args.output else None
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        forecast.to_csv(out, index=False)
        print(f"wrote {out}")
    else:
        print(forecast.to_string(index=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freq", default="D", help="pandas frequency alias (default D)")
    parser.add_argument(
        "--lags",
        type=int,
        nargs="+",
        default=[1, 7],
        help="target lags passed to mlforecast",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    backtest = sub.add_parser("backtest", help="rolling-origin CV metrics")
    backtest.add_argument("input", help="CSV with unique_id, ds, y")
    backtest.add_argument("--horizon", type=int, default=7)
    backtest.add_argument("--windows", type=int, default=3)
    backtest.add_argument("--step-size", type=int, default=None, dest="step_size")
    backtest.add_argument("--json", action="store_true")
    backtest.set_defaults(func=_cmd_backtest)

    predict = sub.add_parser("predict", help="fit and forecast")
    predict.add_argument("input", help="CSV with unique_id, ds, y")
    predict.add_argument("--horizon", type=int, default=14)
    predict.add_argument("-o", "--output", help="optional CSV path for forecasts")
    predict.set_defaults(func=_cmd_predict)

    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ForecastError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
