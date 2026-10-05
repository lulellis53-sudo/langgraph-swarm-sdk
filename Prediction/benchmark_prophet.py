"""Measure Prophet fit and rolling-backtest cost for configurable series counts.

Run with ``uv run --extra forecast python -m Prediction.benchmark_prophet``.
The script records wall-clock measurements; CI tests use a fake Prophet to assert the
deterministic refit count without making timing assertions on shared runners.
"""

from __future__ import annotations

import argparse
import json
import time

import numpy as np
import pandas as pd
from Prediction import ForecastConfig, ForecastEngine


def benchmark(
    series_count: int, observations: int, horizon: int, windows: int
) -> dict[str, float | int]:
    dates = pd.date_range("2024-01-01", periods=observations, freq="D")
    frame = pd.concat(
        [
            pd.DataFrame(
                {
                    "unique_id": f"series-{index}",
                    "ds": dates,
                    "y": 10 + index + np.sin(np.arange(observations) * 2 * np.pi / 7),
                }
            )
            for index in range(series_count)
        ],
        ignore_index=True,
    )
    engine = ForecastEngine(ForecastConfig(model="prophet"))
    start = time.perf_counter()
    engine.fit(frame)
    fit_seconds = time.perf_counter() - start
    start = time.perf_counter()
    engine.backtest(frame, horizon=horizon, n_windows=windows)
    backtest_seconds = time.perf_counter() - start
    return {
        "series": series_count,
        "observations_per_series": observations,
        "horizon": horizon,
        "windows": windows,
        "prophet_fits": series_count * (1 + windows),
        "fit_seconds": round(fit_seconds, 4),
        "backtest_seconds": round(backtest_seconds, 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--series", type=int, nargs="+", default=[1, 5, 20])
    parser.add_argument("--observations", type=int, default=180)
    parser.add_argument("--horizon", type=int, default=14)
    parser.add_argument("--windows", type=int, nargs="+", default=[1, 3, 5])
    args = parser.parse_args()
    results = [
        benchmark(count, args.observations, args.horizon, windows)
        for count in args.series
        for windows in args.windows
    ]
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
