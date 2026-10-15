"""The web-grounded prediction engine: search, extract, forecast, report."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any

from .errors import InsufficientEvidenceError
from .evidence import (
    EvidencePoint,
    dedupe_by_date,
    evidence_snippet,
    pair_dates_numbers,
)
from .forecast import (
    Forecaster,
    ForecastPoint,
    weighted_linear_trend,
)
from .search import SearchTool

if TYPE_CHECKING:
    import pandas as pd
    from mlforecast import MLForecast

__all__ = [
    "ForecastConfig",
    "ForecastEngine",
    "ForecastError",
    "PredictionResult",
    "REQUIRED_COLUMNS",
    "WebPredictionEngine",
]

REQUIRED_COLUMNS = ("unique_id", "ds", "y")


class ForecastError(ValueError):
    """Raised for invalid input data or use of an unfitted engine."""


@dataclass(frozen=True, slots=True)
class ForecastConfig:
    """Model and feature settings for tabular forecasting.

    Attributes:
        freq: Pandas frequency alias of the series ("D", "h", ...).
        lags: Target lags used as features.
        date_features: Calendar features derived from ds.
        lgbm_params: Extra lightgbm.LGBMRegressor keyword arguments.
        model: Optional model backend identifier (e.g. "lgbm", "prophet").
    """

    freq: str = "D"
    lags: tuple[int, ...] = (1, 7)
    date_features: tuple[str, ...] = ("dayofweek", "month")
    lgbm_params: dict[str, Any] = field(default_factory=dict)
    model: str = "lgbm"


def _validate(df: pd.DataFrame, *, min_rows_per_series: int) -> None:
    """Validate tabular time series input data.

    Args:
        df: Input DataFrame containing unique_id, ds, and y columns.
        min_rows_per_series: Minimum required observations per unique_id series.

    Raises:
        ForecastError: If columns are missing, values are NaN, keys are duplicate,
            or series too short.
    """
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ForecastError(f"missing columns: {missing}")
    if df["y"].isna().any():
        raise ForecastError("column 'y' contains NaN")
    if df.duplicated(["unique_id", "ds"]).any():
        raise ForecastError("duplicate (unique_id, ds) rows")
    shortest = int(df.groupby("unique_id").size().min())
    if shortest < min_rows_per_series:
        raise ForecastError(f"need >= {min_rows_per_series} rows per series, got {shortest}")


class ForecastEngine:
    """Fit one global LightGBM model across series, then forecast or backtest."""

    def __init__(self, config: ForecastConfig | None = None) -> None:
        """Initialize the forecast engine with optional configuration.

        Args:
            config: Optional ForecastConfig instance. Defaults to standard daily lags.
        """
        self.config = config or ForecastConfig()
        self._forecaster = self._build()
        self._fitted = False

    def _build(self) -> MLForecast:
        """Construct the underlying MLForecast instance.

        Returns:
            Configured MLForecast instance.
        """
        from lightgbm import LGBMRegressor
        from mlforecast import MLForecast

        params: dict[str, Any] = {"n_estimators": 200, "verbosity": -1, "random_state": 0}
        params.update(self.config.lgbm_params)
        return MLForecast(
            models={"lgbm": LGBMRegressor(**params)},
            freq=self.config.freq,
            lags=list(self.config.lags),
            date_features=list(self.config.date_features),
        )

    @property
    def min_rows_per_series(self) -> int:
        """Smallest series length that leaves at least one training row after lagging."""
        return max(self.config.lags) + 1

    def fit(self, df: pd.DataFrame) -> ForecastEngine:
        """Fit on a long-format frame; returns self.

        Args:
            df: Input DataFrame containing required columns.

        Returns:
            Fitted ForecastEngine instance.

        Raises:
            ForecastError: On missing columns, NaN targets, duplicate keys, or short series.
        """
        _validate(df, min_rows_per_series=self.min_rows_per_series)
        self._forecaster.fit(df[list(REQUIRED_COLUMNS)])
        self._fitted = True
        return self

    def predict(self, horizon: int) -> pd.DataFrame:
        """Forecast horizon steps for every fitted series.

        Args:
            horizon: Number of future time steps to forecast.

        Returns:
            Frame with unique_id, ds, and the lgbm prediction column.

        Raises:
            ForecastError: If the engine is unfitted or horizon is not positive.
        """
        if not self._fitted:
            raise ForecastError("fit() must be called before predict()")
        if horizon < 1:
            raise ForecastError("horizon must be >= 1")
        return self._forecaster.predict(horizon)

    def backtest(self, df: pd.DataFrame, *, horizon: int, n_windows: int = 3) -> pd.DataFrame:
        """Rolling-origin cross-validation; returns per-series MAE, RMSE and sMAPE.

        Args:
            df: Input DataFrame containing history.
            horizon: Step horizon for each cross-validation window.
            n_windows: Number of rolling evaluation windows.

        Returns:
            DataFrame with per-series error metrics.

        Raises:
            ForecastError: On invalid data, horizon < 1, or n_windows < 1.
        """
        if horizon < 1 or n_windows < 1:
            raise ForecastError("horizon and n_windows must be >= 1")
        _validate(df, min_rows_per_series=self.min_rows_per_series + horizon * n_windows)
        cv = self._forecaster.cross_validation(
            df[list(REQUIRED_COLUMNS)], h=horizon, n_windows=n_windows
        )
        err = (cv["y"] - cv["lgbm"]).abs()
        cv = cv.assign(
            abs_err=err,
            sq_err=err**2,
            smape=2 * err / (cv["y"].abs() + cv["lgbm"].abs()).clip(lower=1e-9),
        )
        grouped = cv.groupby("unique_id")
        return (
            grouped.agg(mae=("abs_err", "mean"), mse=("sq_err", "mean"), smape=("smape", "mean"))
            .assign(rmse=lambda f: f["mse"] ** 0.5)
            .drop(columns="mse")
            .reset_index()[["unique_id", "mae", "rmse", "smape"]]
        )



@dataclass(frozen=True, slots=True)
class PredictionResult:
    """Full result of one web-grounded prediction run.

    Attributes:
        query: Primary WebSearch query executed.
        metric: Label identifying the forecast quantity.
        points: Chronological list of deduplicated evidence points gathered.
        forecast: List of forecast points projected forward.
        method: Method name of the active forecaster used.
        warnings: Warnings and notices generated during evidence gathering and synthesis.
    """

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
        """Initialize the web prediction engine.

        Args:
            tool: Search tool returning ``(url, normalized_text)`` documents.
            forecaster: Optional injected :class:`Forecaster` (such as
                :class:`MlForecaster`) for heavier engines; defaults to the
                built-in weighted linear trend.
        """
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
            ValueError: If horizon < 1 or min_points < 3.
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
        """Collect dated numeric observations from every query's documents.

        Args:
            query: Primary search query string.
            extra_queries: Auxiliary query variations to broaden coverage.
            limit: Maximum document count retrieved per query.

        Returns:
            Extracted list of raw evidence points prior to deduplication.
        """
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
        """Return the active forecaster's name for the report.

        Returns:
            String name of the active forecaster.
        """
        if self._forecaster is not None:
            return getattr(self._forecaster, "__name__", type(self._forecaster).__name__)
        return "weighted_linear_trend"

    def _forecast(
        self, points: list[EvidencePoint], horizon: int
    ) -> list[tuple[date, float, float, float]]:
        """Run the injected forecaster or the built-in weighted linear trend.

        Args:
            points: Deduplicated, chronologically sorted evidence points.
            horizon: Number of forward steps to predict.

        Returns:
            List of (date, value, low, high) forecast step tuples.
        """
        if self._forecaster is not None:
            return list(self._forecaster(points, horizon))
        return weighted_linear_trend(points, horizon)
