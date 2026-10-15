"""Tests for the Prediction ForecastEngine using hypothesis property testing."""

from __future__ import annotations

import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from Modules.Prediction.engine import ForecastConfig, ForecastEngine


@settings(deadline=None)
@given(
    st.lists(
        st.floats(allow_nan=False, allow_infinity=False),
        min_size=10,
        max_size=50,
    )
)
def test_forecast_engine_fit(values: list[float]) -> None:
    """Verify that ForecastEngine fits and generates predictions for numeric sequences.

    Args:
        values: Generated list of floats representing time series observations.

    Returns:
        None.
    """
    dates = pd.date_range("2020-01-01", periods=len(values), freq="D")
    data = {"unique_id": "id1", "ds": dates, "y": values}
    df = pd.DataFrame(data)
    if len(df) < 10:
        return
    df["ds"] = pd.to_datetime(df["ds"])
    df = df.sort_values(["unique_id", "ds"])

    config = ForecastConfig(lags=(1, 2))
    engine = ForecastEngine(config)
    engine.fit(df)

    assert engine._fitted

    predictions = engine.predict(5)
    assert len(predictions) == 5
    assert "unique_id" in predictions.columns
    assert "ds" in predictions.columns
    assert "lgbm" in predictions.columns
