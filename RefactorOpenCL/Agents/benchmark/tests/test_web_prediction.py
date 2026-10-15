"""Tests for the web-grounded prediction engine (offline, deterministic)."""

from __future__ import annotations

from datetime import date

import pytest
import swarm_sdk.prediction as wp
from swarm_sdk.prediction import (
    EtsForecaster,
    EvidencePoint,
    InsufficientEvidenceError,
    MlForecaster,
    PredictionError,
    WebPredictionEngine,
    WebSearchToolError,
    make_websearch_tool,
    prophet_forecaster,
    seasonal_naive,
    to_forecast_frame,
)
from swarm_sdk.prediction.evidence import pair_dates_numbers
from swarm_sdk.prediction.forecast import weighted_linear_trend

_DOCS = [
    (
        "https://example.com/report-a",
        "As of 2026-01-01, the index was 100.0. On 2026-02-01 the index hit 110.0. "
        "By 2026-03-01, the index reached 121.0.",
    ),
    (
        "https://example.com/report-b",
        "The value stood at 999 in 2019, which is too old to parse as a date here. "
        "On 5 March 2026 observers recorded 119.5.",
    ),
    ("https://example.com/noise", "No dated numbers live in this document at all."),
]


def _fake_tool(docs: list[tuple[str, str]] | None = None):
    """Return a tool call serving fixed documents and recording queries."""
    served = docs if docs is not None else _DOCS
    calls: list[str] = []

    def tool(query: str, *, limit: int = 5) -> list[tuple[str, str]]:
        calls.append(query)
        return served[:limit]

    tool.calls = calls  # type: ignore[attr-defined]
    return tool


def test_pair_dates_numbers_extracts_iso_and_textual_dates() -> None:
    pairs = pair_dates_numbers(_DOCS[0][1])
    assert pairs == [
        (date(2026, 1, 1), 100.0),
        (date(2026, 2, 1), 110.0),
        (date(2026, 3, 1), 121.0),
    ]
    textual = pair_dates_numbers(_DOCS[1][1])
    assert (date(2026, 3, 5), 119.5) in textual
    # The 2019 bare year is not a full date; nothing may pair with it.
    assert all(point.year == 2026 for point, _ in textual)


def test_pair_dates_numbers_handles_portuguese_and_dot_thousands() -> None:
    text = (
        "Em 12 de agosto de 2026 o preço era R$ 14.499, "
        "e em 5 de setembro de 2026 caiu para R$ 13.999."
    )
    pairs = pair_dates_numbers(text, decimal_comma=True)
    assert pairs == [(date(2026, 8, 12), 14499.0), (date(2026, 9, 5), 13999.0)]


def test_weighted_linear_trend_validates_inputs() -> None:
    points = [
        EvidencePoint(date(2026, 1, 1), 1.0, "u", "s"),
        EvidencePoint(date(2026, 1, 2), 2.0, "u", "s"),
    ]
    steps = weighted_linear_trend(points, 1)
    assert len(steps) == 1 and steps[0][1] > 1.0
    with pytest.raises(ValueError):
        weighted_linear_trend(points[:1], 1)
    with pytest.raises(ValueError):
        weighted_linear_trend(points, 0)


def test_engine_builds_series_and_forecasts_linear_trend() -> None:
    engine = WebPredictionEngine(_fake_tool())
    result = engine.predict("metric by month 2026", metric="index", horizon=2)

    assert [point.value for point in result.points] == [100.0, 110.0, 121.0, 119.5]
    assert result.method == "weighted_linear_trend"
    assert len(result.forecast) == 2
    first, second = result.forecast
    assert first.value < second.value  # upward trend continues
    assert first.low < first.value < first.high
    assert first.date == date(2026, 3, 6)  # horizon starts after the last observation
    assert second.date == date(2026, 3, 7)
    assert "https://example.com/report-a" in {point.source_url for point in result.points}


def test_engine_merges_evidence_from_extra_queries() -> None:
    calls: list[str] = []

    def serving(query: str, *, limit: int = 5) -> list[tuple[str, str]]:
        calls.append(query)
        if "q2" in query:
            return [("https://extra.example/1", "On 2026-04-01 the index was 130.0.")]
        return _DOCS

    result = WebPredictionEngine(serving).predict(
        "metric 2026 q1", extra_queries=("metric 2026 q2",), horizon=1
    )
    assert calls == ["metric 2026 q1", "metric 2026 q2"]
    assert result.points[-1].value == 130.0
    assert result.points[-1].date == date(2026, 4, 1)


def test_engine_dedupes_conflicting_same_day_values_with_warning() -> None:
    docs = [
        ("https://a.example/1", "On 2026-01-01 the level was 10.0."),
        ("https://b.example/1", "On 2026-01-01 the level was 20.0."),
        ("https://c.example/1", "On 2026-01-01 the level was 30.0."),
        ("https://d.example/1", "On 2026-02-01 the level was 25.0."),
        ("https://e.example/1", "On 2026-03-01 the level was 31.0."),
    ]
    result = WebPredictionEngine(_fake_tool(docs)).predict("level", horizon=1)
    assert len(result.points) == 3
    assert result.points[0].value == 20.0  # median of 10/20/30
    assert any("conflicting" in warning for warning in result.warnings)


def test_engine_raises_on_insufficient_evidence() -> None:
    docs = [("https://a.example/1", "On 2026-01-01 the level was 10.0.")]
    with pytest.raises(InsufficientEvidenceError):
        WebPredictionEngine(_fake_tool(docs)).predict("level", horizon=1)


def test_engine_propagates_tool_failure() -> None:
    def broken_tool(query: str, *, limit: int = 5) -> list[tuple[str, str]]:
        raise RuntimeError("network down")

    with pytest.raises(RuntimeError):
        WebPredictionEngine(broken_tool).predict("level", horizon=1)


def test_injected_forecaster_is_used_and_named() -> None:
    def heavy_forecaster(points: list[EvidencePoint], horizon: int):
        last = points[-1]
        return [(last.date, last.value + 1000.0, last.value, last.value + 2000.0)]

    result = WebPredictionEngine(_fake_tool(), forecaster=heavy_forecaster).predict(
        "metric", horizon=1
    )
    assert result.method == "heavy_forecaster"
    assert result.forecast[0].value == result.points[-1].value + 1000.0


def test_to_forecast_frame_needs_pandas(monkeypatch) -> None:
    import builtins

    real_import = builtins.__import__

    def no_pandas(name: str, *args, **kwargs):
        if name == "pandas":
            raise ImportError("pandas unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_pandas)
    points = [
        EvidencePoint(date(2026, 1, 1), 1.0, "u", "s"),
        EvidencePoint(date(2026, 1, 2), 2.0, "u", "s"),
    ]
    with pytest.raises(PredictionError, match="forecast"):
        to_forecast_frame(points)


def test_ml_forecaster_maps_stub_engine_rows(monkeypatch) -> None:
    from collections import namedtuple

    Row = namedtuple("Row", ["unique_id", "ds", "lightgbm"])

    class StubFrame:
        columns = ["unique_id", "ds", "lightgbm"]

        def itertuples(self, *, index: bool) -> list[tuple]:
            assert index is False
            return [
                Row("web", date(2026, 1, 3), 33.5),
                Row("web", date(2026, 1, 2), 32.5),
            ]

    class StubEngine:
        def fit(self, frame: object) -> StubEngine:
            return self

        def predict(self, horizon: int, **kwargs: object) -> StubFrame:
            assert horizon == 2
            return StubFrame()

    sentinel_frame = object()
    monkeypatch.setattr(
        "swarm_sdk.prediction.forecast.to_forecast_frame",
        lambda points, metric="web": sentinel_frame,
    )
    points = [
        EvidencePoint(date(2026, 1, 1), 10.0, "u", "s"),
        EvidencePoint(date(2026, 1, 2), 11.0, "u", "s"),
    ]
    result = MlForecaster(StubEngine)(points, 2)
    assert result == [
        (date(2026, 1, 2), 32.5, 32.5, 32.5),
        (date(2026, 1, 3), 33.5, 33.5, 33.5),
    ]


def test_ml_forecaster_reports_missing_worktree(monkeypatch) -> None:
    import builtins

    real_import = builtins.__import__

    def no_prediction(name: str, *args, **kwargs):
        if name == "Prediction":
            raise ImportError("worktree unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_prediction)
    points = [
        EvidencePoint(date(2026, 1, 1), 1.0, "u", "s"),
        EvidencePoint(date(2026, 1, 2), 2.0, "u", "s"),
    ]
    with pytest.raises(PredictionError, match="ForecastEngine"):
        MlForecaster()(points, 1)


def test_make_websearch_tool_fails_cleanly_without_worktree(monkeypatch) -> None:
    import builtins

    real_import = builtins.__import__

    def no_websearch(name: str, *args, **kwargs):
        if name.startswith("WebSearch"):
            raise ImportError("worktree unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_websearch)
    with pytest.raises(WebSearchToolError):
        make_websearch_tool()


def _weekly_points(days: int = 21, *, base: float = 10.0) -> list[EvidencePoint]:
    """Build a deterministic series with an exact 7-day seasonal pattern."""
    return [
        EvidencePoint(date(2026, 1, 1 + offset), base + float(offset % 7), "u", "s")
        for offset in range(days)
    ]


def test_seasonal_naive_repeats_the_weekly_pattern() -> None:
    points = _weekly_points(21)
    steps = seasonal_naive(points, 3)
    assert [step[0] for step in steps] == [date(2026, 1, 22), date(2026, 1, 23), date(2026, 1, 24)]
    # 21-day series with period 7: zero seasonal differences -> exact band.
    assert steps[0][1] == pytest.approx(points[-7].value)
    assert steps[1][1] == pytest.approx(points[-6].value)
    assert steps[2][1] == pytest.approx(points[-5].value)
    assert steps[0][2] == pytest.approx(steps[0][1])
    with pytest.raises(ValueError):
        seasonal_naive(points[:5], 1)


def test_ets_forecaster_fits_and_gives_model_intervals() -> None:
    pytest.importorskip("statsmodels", reason="forecast extra not synced")
    points = [
        EvidencePoint(
            date(2026, 1, 1 + offset),
            10.0 + 0.5 * offset + 2.0 * (offset % 7),
            "u",
            "s",
        )
        for offset in range(30)
    ]
    steps = EtsForecaster()(points, 3)
    assert len(steps) == 3
    assert all(low <= value <= high for _, value, low, high in steps)
    assert all(low < high for _, _, low, high in steps)


def test_prophet_forecaster_wires_the_prophet_engine() -> None:
    forecaster = prophet_forecaster()
    assert isinstance(forecaster, MlForecaster)
    pytest.importorskip("prophet", reason="forecast extra not synced")
    engine = forecaster._make_engine()
    assert engine.config.model == "prophet"


def test_prophet_forecaster_reports_missing_worktree(monkeypatch) -> None:
    import builtins

    real_import = builtins.__import__

    def no_prediction(name: str, *args, **kwargs):
        if name == "Prediction":
            raise ImportError("worktree unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_prediction)
    points = _weekly_points(10)
    with pytest.raises(PredictionError, match="worktree engine"):
        prophet_forecaster()(points, 1)


def test_public_api_surface_is_stable() -> None:
    assert set(wp.__all__) == {
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
    }
