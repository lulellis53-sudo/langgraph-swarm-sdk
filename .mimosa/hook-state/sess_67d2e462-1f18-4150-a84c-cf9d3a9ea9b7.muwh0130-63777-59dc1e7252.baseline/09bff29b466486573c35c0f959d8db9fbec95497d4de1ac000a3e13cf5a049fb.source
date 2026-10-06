"""Offline ``ForecastEngine`` backtest on synthetic multi-series sine data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from Prediction import ForecastEngine

_RESULTS = Path(__file__).resolve().parents[2] / "results" / "prediction_forecast"


def _synthetic_frame(*, n: int = 120, series: tuple[str, ...] = ("a", "b")) -> pd.DataFrame:
    ds = pd.date_range("2026-01-01", periods=n, freq="D")
    parts: list[pd.DataFrame] = []
    for i, uid in enumerate(series):
        weekly = np.sin(2 * np.pi * np.arange(n) / 7)
        parts.append(pd.DataFrame({"unique_id": uid, "ds": ds, "y": 10 * (i + 1) + 3 * weekly}))
    return pd.concat(parts, ignore_index=True)


def run(*, quick: bool = False) -> dict[str, Any]:
    """Run backtest; ``quick`` uses fewer rows/windows for CI."""
    n = 100 if quick else 120
    n_windows = 2 if quick else 3
    df = _synthetic_frame(n=n)
    metrics = ForecastEngine().backtest(df, horizon=7, n_windows=n_windows)
    mean_mae = float(metrics["mae"].mean())
    mean_rmse = float(metrics["rmse"].mean())
    return {
        "task": "prediction_forecast",
        "metrics": [
            {
                "name": "mae",
                "current": round(mean_mae, 6),
                "higher_is_better": False,
            },
            {
                "name": "rmse",
                "current": round(mean_rmse, 6),
                "higher_is_better": False,
            },
        ],
        "mean_mae": mean_mae,
        "per_series": metrics.to_dict(orient="records"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-results", action="store_true")
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    report = run(quick=args.quick)
    print(json.dumps(report, indent=2))
    if args.write_results:
        _RESULTS.mkdir(parents=True, exist_ok=True)
        out = _RESULTS / "latest.json"
        out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {out}")


if __name__ == "__main__":
    main()
