"""Web-grounded prediction engine.

Forecasts a metric from time-stamped numeric evidence gathered by calling the
``WebSearch`` worktree as a tool: search hits are fetched, extracted, and
normalized by the WebSearch pipeline, dates and numbers are pulled from the
normalized text into an evidence series, and a forecaster produces the
prediction. The built-in weighted linear trend needs no optional dependency;
:class:`MlForecaster` bridges the same evidence into the worktree
``Prediction.ForecastEngine`` (``uv sync --extra forecast``).

Public API:

    from swarm_sdk.prediction import WebPredictionEngine, make_websearch_tool
"""

from __future__ import annotations

from swarm_sdk.prediction.engine import PredictionResult, WebPredictionEngine
from swarm_sdk.prediction.errors import (
    InsufficientEvidenceError,
    PredictionError,
    WebSearchToolError,
)
from swarm_sdk.prediction.evidence import EvidencePoint
from swarm_sdk.prediction.forecast import (
    EtsForecaster,
    Forecaster,
    ForecastPoint,
    MlForecaster,
    PredictionFrame,
    prophet_forecaster,
    seasonal_naive,
    to_forecast_frame,
)
from swarm_sdk.prediction.search import SearchTool, make_websearch_tool

__all__ = [
    "EvidencePoint",
    "EtsForecaster",
    "Forecaster",
    "ForecastPoint",
    "InsufficientEvidenceError",
    "MlForecaster",
    "PredictionError",
    "PredictionFrame",
    "PredictionResult",
    "SearchTool",
    "WebPredictionEngine",
    "WebSearchToolError",
    "make_websearch_tool",
    "prophet_forecaster",
    "seasonal_naive",
    "to_forecast_frame",
]
