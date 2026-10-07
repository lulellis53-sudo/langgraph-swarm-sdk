"""The web-grounded prediction engine: search, extract, forecast, report."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from swarm_sdk.prediction.errors import InsufficientEvidenceError
from swarm_sdk.prediction.evidence import (
    EvidencePoint,
    dedupe_by_date,
    evidence_snippet,
    pair_dates_numbers,
)
from swarm_sdk.prediction.forecast import (
    Forecaster,
    ForecastPoint,
    weighted_linear_trend,
)
from swarm_sdk.prediction.search import SearchTool

__all__ = ["PredictionResult", "WebPredictionEngine"]


@dataclass(frozen=True, slots=True)
class PredictionResult:
    """Full result of one web-grounded prediction run."""

    query: str
    metric: str
    points: list[EvidencePoint]
    forecast: list[ForecastPoint]
    method: str
    warnings: list[str]


class WebPredictionEngine:
    """Forecast a metric from evidence gathered by a search tool call.

    Args:
        tool: Search tool returning ``(url, normalized_text)`` documents. Use
            :func:`make_websearch_tool` for the real WebSearch worktree, or a
            fake in tests.
        forecaster: Optional injected :class:`Forecaster` (such as
            :class:`MlForecaster`) for heavier engines; defaults to the
            built-in weighted linear trend.
    """

    def __init__(self, tool: SearchTool, forecaster: Forecaster | None = None) -> None:
        self._tool = tool
        self._forecaster = forecaster

    def predict(
        self,
        query: str,
        *,
        metric: str = "value",
        horizon: int = 3,
        min_points: int = 3,
        limit: int = 5,
        extra_queries: Sequence[str] = (),
    ) -> PredictionResult:
        """Search, extract evidence, and forecast ``horizon`` steps ahead.

        Args:
            query: Primary WebSearch query; the engine appends nothing, so
                include date-bearing phrasing yourself (e.g.
                ``"metric by month 2026"``).
            metric: Label for the forecast quantity.
            horizon: Steps (days) to forecast beyond the last observation.
            min_points: Minimum distinct dated observations required.
            limit: Maximum documents fetched per tool call.
            extra_queries: Additional query variants; evidence from all queries
                is merged (same-day conflicts resolve to the median).

        Returns:
            :class:`PredictionResult` with evidence, forecast, and warnings.

        Raises:
            InsufficientEvidenceError: Fewer than ``min_points`` usable observations.
            WebSearchToolError: The tool call itself failed.
        """
        if horizon < 1 or min_points < 3:
            raise ValueError("horizon must be >= 1 and min_points must be >= 3")
        warnings: list[str] = []
        points = self._gather_evidence(query, extra_queries, limit)
        points = dedupe_by_date(points, warnings)
        if len(points) < min_points:
            raise InsufficientEvidenceError(
                f"only {len(points)} dated observations for query {query!r}; need {min_points}"
            )
        steps = self._forecast(points, horizon)
        return PredictionResult(
            query=query,
            metric=metric,
            points=points,
            forecast=[
                ForecastPoint(point_date, value, low, high)
                for point_date, value, low, high in steps
            ],
            method=self._method_name(),
            warnings=warnings,
        )

    def _gather_evidence(
        self, query: str, extra_queries: Sequence[str], limit: int
    ) -> list[EvidencePoint]:
        """Collect dated numeric observations from every query's documents."""
        points: list[EvidencePoint] = []
        for current_query in (query, *extra_queries):
            for url, text in self._tool(current_query, limit=limit):
                for point_date, value in pair_dates_numbers(text):
                    points.append(
                        EvidencePoint(
                            date=point_date,
                            value=value,
                            source_url=url,
                            snippet=evidence_snippet(text, point_date),
                        )
                    )
        return points

    def _method_name(self) -> str:
        """Return the active forecaster's name for the report."""
        if self._forecaster is not None:
            return getattr(self._forecaster, "__name__", type(self._forecaster).__name__)
        return "weighted_linear_trend"

    def _forecast(self, points: list[EvidencePoint], horizon: int) -> list[tuple]:
        """Run the injected forecaster or the built-in weighted linear trend."""
        if self._forecaster is not None:
            return list(self._forecaster(points, horizon))
        return weighted_linear_trend(points, horizon)
