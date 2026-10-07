"""Forecasting engine: fit/predict, backtest and input validation."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from Prediction import ForecastConfig, ForecastEngine, ForecastError


def _frame(n: int = 120, series: tuple[str, ...] = ("a", "b")) -> pd.DataFrame:
    ds = pd.date_range("2026-01-01", periods=n, freq="D")
    parts = []
    for i, uid in enumerate(series):
        weekly = np.sin(2 * np.pi * np.arange(n) / 7)
        parts.append(pd.DataFrame({"unique_id": uid, "ds": ds, "y": 10 * (i + 1) + 3 * weekly}))
    return pd.concat(parts, ignore_index=True)


def test_predict_returns_horizon_rows_per_series() -> None:
    engine = ForecastEngine().fit(_frame())
    out = engine.predict(7)
    assert len(out) == 14
    assert set(out["unique_id"]) == {"a", "b"}
    assert out["ds"].min() == pd.Timestamp("2026-05-01")
    assert np.isfinite(out["lgbm"]).all()


def test_forecast_tracks_weekly_seasonality() -> None:
    frame = _frame()
    out = ForecastEngine().fit(frame).predict(7)
    truth = 10 + 3 * np.sin(2 * np.pi * np.arange(120, 127) / 7)
    got = out[out["unique_id"] == "a"]["lgbm"].to_numpy()
    assert np.abs(got - truth).mean() < 1.0


def test_backtest_reports_small_error_on_clean_signal() -> None:
    metrics = ForecastEngine().backtest(_frame(), horizon=7, n_windows=2)
    assert list(metrics.columns) == ["unique_id", "mae", "rmse", "smape"]
    assert (metrics["mae"] < 1.0).all()


def test_backtest_respects_custom_step_size() -> None:
    frame = _frame(n=140)
    metrics = ForecastEngine(
        ForecastConfig(step_size=14),
    ).backtest(frame, horizon=7, n_windows=2, step_size=14)
    assert len(metrics) == 2


def test_lag_transforms_smoke() -> None:
    from mlforecast.lag_transforms import RollingMean

    config = ForecastConfig(lag_transforms={7: [RollingMean(window_size=7)]})
    metrics = ForecastEngine(config).backtest(_frame(n=140), horizon=7, n_windows=2)
    assert (metrics["mae"] < 2.0).all()


def test_predict_before_fit_raises() -> None:
    with pytest.raises(ForecastError, match="fit"):
        ForecastEngine().predict(3)


def test_invalid_horizon_raises() -> None:
    engine = ForecastEngine().fit(_frame())
    with pytest.raises(ForecastError, match="horizon"):
        engine.predict(0)


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda f: f.drop(columns="y"), "missing columns"),
        (lambda f: f.assign(y=f["y"].where(f.index != 3)), "NaN"),
        (lambda f: pd.concat([f, f.iloc[:1]]), "duplicate"),
        (lambda f: f.groupby("unique_id").head(5), "rows per series"),
    ],
)
def test_invalid_input_is_rejected(mutate, match: str) -> None:
    with pytest.raises(ForecastError, match=match):
        ForecastEngine().fit(mutate(_frame()))


def test_package_exports_forecast_engine() -> None:
    from Prediction import ForecastConfig, ForecastEngine, ForecastError, LanceForecastStore

    assert ForecastEngine is not None
    assert ForecastConfig is not None
    assert ForecastError is not None
    assert LanceForecastStore is not None


def test_lance_store_roundtrip(tmp_path) -> None:
    lancedb = pytest.importorskip("lancedb")
    del lancedb  # used only to skip when extra is missing

    from Prediction import LanceForecastStore

    engine = ForecastEngine().fit(_frame(n=80))
    forecast = engine.predict(5)
    store = LanceForecastStore(str(tmp_path / "forecasts.lance"))
    run_id = store.append_forecasts(forecast)
    saved = store.read_run(run_id, limit=20)
    assert len(saved) == len(forecast)
    assert set(saved["unique_id"]) == set(forecast["unique_id"])
    meta = store.describe_run(run_id)
    assert meta.run_id == run_id
    assert meta.row_count == len(forecast)
