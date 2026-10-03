"""Forecasting engine: fit/predict, backtest and input validation."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from Prediction import ForecastEngine, ForecastError


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
    assert out["ds"].min() == pd.Timestamp("2026-01-01") + pd.Timedelta(days=120)
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
