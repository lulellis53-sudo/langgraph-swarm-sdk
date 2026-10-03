"""Forecasting engine: fit/predict, backtest and input validation."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from Prediction import (
    ForecastConfig,
    ForecastEngine,
    ForecastError,
    TextFeatureConfig,
    TextFeatureTransformer,
)


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


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda f: f.assign(unique_id=f["unique_id"].where(f.index != 0)), "unique_id.*null"),
        (lambda f: f.assign(ds=f["ds"].where(f.index != 0)), "ds.*NaT"),
        (lambda f: f.assign(y=np.inf), "infinite"),
        (lambda f: f.assign(y="not-a-number"), "numeric"),
        (lambda f: f.iloc[0:0], "at least one row"),
    ],
)
def test_invalid_values_are_rejected(mutate, match: str) -> None:
    with pytest.raises(ForecastError, match=match):
        ForecastEngine().fit(mutate(_frame()))


@pytest.mark.parametrize(
    ("config", "match"),
    [
        (ForecastConfig(lags=()), "lags"),
        (ForecastConfig(lags=(1, 1)), "duplicates"),
        (ForecastConfig(step_size=0), "step_size"),
        (ForecastConfig(lag_transforms={0: []}), "lag_transforms"),
    ],
)
def test_invalid_config_is_rejected(config: ForecastConfig, match: str) -> None:
    with pytest.raises(ForecastError, match=match):
        ForecastEngine(config)


def test_lag_transforms_accepted_by_config() -> None:
    from mlforecast.lag_transforms import RollingMean

    config = ForecastConfig(lag_transforms={7: [RollingMean(window_size=7)]})
    out = ForecastEngine(config).fit(_frame()).predict(3)
    assert len(out) == 6


def test_backtest_step_size_requires_enough_rows() -> None:
    with pytest.raises(ForecastError, match="rows per series"):
        ForecastEngine().backtest(_frame(n=28), horizon=7, n_windows=3, step_size=7)


def test_random_forest_parameters_are_backend_specific() -> None:
    frame = _frame(n=48, series=("a",))
    engine = ForecastEngine(
        ForecastConfig(
            model="sklearn-random-forest",
            random_forest_params={"n_estimators": 8, "max_depth": 3},
        )
    ).fit(frame)
    assert len(engine.predict(2)) == 2


def test_polars_input_and_output() -> None:
    pl = pytest.importorskip("polars")
    frame = _frame(n=48, series=("a",))
    polars_frame = pl.DataFrame(frame.to_dict(orient="list"))
    result = ForecastEngine().fit(polars_frame).predict(2, output="polars")
    assert isinstance(result, pl.DataFrame)
    assert result.height == 2


def test_arrow_output() -> None:
    pytest.importorskip("pyarrow")
    engine = ForecastEngine().fit(_frame(n=48, series=("a",)))
    result = engine.predict(2, output="arrow")
    assert result.num_rows == 2
    assert "lgbm" in result.column_names


def test_text_embeddings_attach_by_row_identity() -> None:
    frame = _frame(n=4, series=("a",))
    frame["summary"] = ["first", "second", "third", "fourth"]
    transformer = TextFeatureTransformer(TextFeatureConfig(backend="transformers"))

    class FakeModel:
        def encode(self, texts, **kwargs):
            return np.array([[len(text), index] for index, text in enumerate(texts)])

    transformer._model = FakeModel()
    result = transformer.attach(frame.iloc[::-1], text_column="summary")
    assert result["ds"].tolist() == frame.iloc[::-1]["ds"].tolist()
    assert result["text_embedding_0"].tolist() == [6, 5, 6, 5]


def test_exogenous_embeddings_are_required_for_forecast() -> None:
    frame = _frame(n=48, series=("a",))
    frame["text_embedding_0"] = np.arange(len(frame), dtype=float)
    engine = ForecastEngine(ForecastConfig(exogenous_features=("text_embedding_0",))).fit(frame)
    with pytest.raises(ForecastError, match="future_features are required"):
        engine.predict(2)
    future = pd.DataFrame(
        {
            "unique_id": ["a", "a"],
            "ds": pd.date_range(frame["ds"].max(), periods=3, freq="D")[1:],
            "text_embedding_0": [48.0, 49.0],
        }
    )
    result = engine.predict(2, future_features=future)
    assert len(result) == 2
    metrics = engine.backtest(frame, horizon=2, n_windows=2)
    assert list(metrics.columns) == ["unique_id", "mae", "rmse", "smape"]


def test_prophet_refit_count_scales_with_series_and_windows(monkeypatch) -> None:
    import sys
    import types

    class FakeProphet:
        fit_count = 0

        def __init__(self, **kwargs):
            pass

        def add_regressor(self, name):
            pass

        def fit(self, frame):
            type(self).fit_count += 1
            self.last_ds = frame["ds"].max()
            return self

        def make_future_dataframe(self, periods, freq, include_history):
            return pd.DataFrame(
                {"ds": pd.date_range(self.last_ds, periods=periods + 1, freq=freq)[1:]}
            )

        def predict(self, frame):
            return frame.assign(yhat=1.0)

    monkeypatch.setitem(sys.modules, "prophet", types.SimpleNamespace(Prophet=FakeProphet))
    frame = _frame(n=48, series=("a", "b"))
    engine = ForecastEngine(ForecastConfig(model="prophet")).fit(frame)
    forecast = engine.predict(2)
    assert len(forecast) == 4
    engine.backtest(frame, horizon=2, n_windows=3)
    assert FakeProphet.fit_count == 2 + (2 * 3)
