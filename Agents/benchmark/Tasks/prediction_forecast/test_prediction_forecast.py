"""CI gate for the prediction_forecast benchmark task."""

from __future__ import annotations

from benchmark.Tasks.prediction_forecast.benchmark_prediction_forecast import run


def test_prediction_forecast_quick_mae_gate() -> None:
    report = run(quick=True)
    names = [m["name"] for m in report["metrics"]]
    assert names == ["mae", "rmse"]
    mae = next(m for m in report["metrics"] if m["name"] == "mae")
    assert mae["current"] < 2.0
