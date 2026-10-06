"""Forecasters over evidence points: trend, seasonal, ETS, Prophet, and the ML bridge."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol

from swarm_sdk.prediction._worktree import ensure_repo_on_path
from swarm_sdk.prediction.errors import PredictionError
from swarm_sdk.prediction.evidence import EvidencePoint

__all__ = [
    "EtsForecaster",
    "ForecastPoint",
    "Forecaster",
    "MlForecaster",
    "PredictionFrame",
    "prophet_forecaster",
    "seasonal_naive",
    "to_forecast_frame",
    "weighted_linear_trend",
]

#: Normal-approximation half-width multiplier (~80% two-sided).
_Z_APPROX = 1.28


@dataclass(frozen=True, slots=True)
class ForecastPoint:
    """One forecast step with its residual interval."""

    date: date
    value: float
    low: float
    high: float


class Forecaster(Protocol):
    """A callable forecasting ``horizon`` steps from evidence points.

    Returns ``(date, value, low, high)`` tuples; ``low``/``high`` may equal
    ``value`` when the model emits point forecasts only.
    """

    def __call__(
        self, points: Sequence[EvidencePoint], horizon: int
    ) -> list[tuple[date, float, float, float]]: ...


def weighted_linear_trend(
    points: Sequence[EvidencePoint], horizon: int
) -> list[tuple[date, float, float, float]]:
    """Forecast with a recency-weighted linear trend over day ordinals.

    Later observations weigh more; the interval is ``value ± 1.28`` residual
    standard deviations, a ~80% normal approximation — not a calibrated
    confidence interval.

    Args:
        points: At least two evidence points sorted by date.
        horizon: Steps (days) to forecast beyond the last observation.

    Returns:
        ``(date, value, low, high)`` tuples for each forecast day.

    Raises:
        ValueError: Fewer than two points or a non-positive horizon.
    """
    if len(points) < 2 or horizon < 1:
        raise ValueError("weighted_linear_trend needs >= 2 points and horizon >= 1")
    last_date = points[-1].date
    ordinals = [float(point.date.toordinal()) for point in points]
    values = [point.value for point in points]
    count = len(values)
    weights = [float(position + 1) for position in range(count)]
    weight_sum = sum(weights)
    mean_x = sum(weight * x for weight, x in zip(weights, ordinals, strict=True)) / weight_sum
    mean_y = sum(weight * y for weight, y in zip(weights, values, strict=True)) / weight_sum
    variance = sum(weight * (x - mean_x) ** 2 for weight, x in zip(weights, ordinals, strict=True))
    if variance <= 0.0:
        slope = 0.0
    else:
        slope = (
            sum(
                weight * (x - mean_x) * (y - mean_y)
                for weight, x, y in zip(weights, ordinals, values, strict=True)
            )
            / variance
        )
    intercept = mean_y - slope * mean_x
    residuals = [y - (slope * x + intercept) for x, y in zip(ordinals, values, strict=True)]
    residual_std = (sum(res * res for res in residuals) / max(count - 2, 1)) ** 0.5
    half_width = _Z_APPROX * residual_std
    steps: list[tuple[date, float, float, float]] = []
    for step in range(1, horizon + 1):
        step_date = last_date + timedelta(days=step)
        fitted = slope * float(step_date.toordinal()) + intercept
        steps.append((step_date, fitted, fitted - half_width, fitted + half_width))
    return steps


def seasonal_naive(
    points: Sequence[EvidencePoint], horizon: int, *, period: int = 7
) -> list[tuple[date, float, float, float]]:
    """Forecast by repeating the value one period back (seasonal naive baseline).

    The interval width is ``± 1.28`` standard deviations of the one-period
    differences — the same ~80% normal approximation as the trend forecaster.
    Zero dependency; the reference baseline for weekly patterns in web evidence.

    Args:
        points: At least ``period + 1`` evidence points sorted by date.
        horizon: Steps (days) to forecast beyond the last observation.
        period: Season length in days (7 = weekly).

    Returns:
        ``(date, value, low, high)`` tuples for each forecast day.

    Raises:
        ValueError: Too few points, or a non-positive horizon or period.
    """
    if period < 1 or horizon < 1 or len(points) <= period:
        raise ValueError("seasonal_naive needs period >= 1, horizon >= 1, and > period points")
    values = [point.value for point in points]
    differences = [later - earlier for earlier, later in zip(values, values[period:], strict=False)]
    residual_std = (sum(diff * diff for diff in differences) / max(len(differences) - 1, 1)) ** 0.5
    half_width = _Z_APPROX * residual_std
    steps: list[tuple[date, float, float, float]] = []
    for step in range(1, horizon + 1):
        step_date = points[-1].date + timedelta(days=step)
        value = values[-period + (step - 1) % period]
        steps.append((step_date, value, value - half_width, value + half_width))
    return steps


class EtsForecaster:
    """ETS exponential smoothing (damped additive trend) via statsmodels.

    Weekly seasonality joins when at least two full periods of daily evidence
    exist. Intervals come from the model's prediction interval
    (``ETSModel.get_prediction(...).summary_frame``), so they are model based,
    not approximated. statsmodels and pandas import lazily (forecast extra).

    Raises:
        PredictionError: statsmodels is missing, or the fit fails to converge
            into a usable model.
    """

    #: Minimum daily observations before weekly seasonality is enabled.
    _SEASONAL_MIN_ROWS = 14

    def __init__(self, *, period: int = 7, alpha: float = 0.2) -> None:
        """Configure the seasonal length and interval alpha."""
        if period < 1:
            raise ValueError("period must be >= 1")
        if not 0.0 < alpha < 1.0:
            raise ValueError("alpha must be in (0, 1)")
        self._period = period
        self._alpha = alpha

    def __call__(
        self, points: Sequence[EvidencePoint], horizon: int
    ) -> list[tuple[date, float, float, float]]:
        """Fit damped-trend ETS on ``points`` and forecast ``horizon`` steps."""
        try:
            import numpy as np
            import pandas as pd
            from statsmodels.tsa.exponential_smoothing.ets import ETSModel
        except ImportError as err:
            raise PredictionError(
                "EtsForecaster needs statsmodels: run `uv sync --extra forecast`"
            ) from err
        if horizon < 1 or len(points) < 3:
            raise ValueError("EtsForecaster needs >= 3 points and horizon >= 1")
        values = [float(point.value) for point in points]
        seasonal = "add" if len(points) >= self._SEASONAL_MIN_ROWS + self._period else None
        try:
            fit = ETSModel(
                pd.Series(values),
                error="add",
                trend="add",
                damped_trend=True,
                seasonal=seasonal,
                seasonal_periods=self._period if seasonal else None,
                initialization_method="estimated",
            ).fit(disp=False)
            frame = fit.get_prediction(
                start=len(values), end=len(values) + horizon - 1
            ).summary_frame(alpha=self._alpha)
        except (ValueError, np.linalg.LinAlgError) as err:
            raise PredictionError(f"ETS fit failed: {type(err).__name__}") from err
        steps: list[tuple[date, float, float, float]] = []
        for offset in range(horizon):
            row = frame.iloc[offset]
            step_date = points[-1].date + timedelta(days=offset + 1)
            steps.append(
                (
                    step_date,
                    float(row["mean"]),
                    float(row["pi_lower"]),
                    float(row["pi_upper"]),
                )
            )
        return steps


def prophet_forecaster() -> MlForecaster:
    """Return an :class:`MlForecaster` driving the worktree engine on Prophet.

    Prophet adds changepoint-flexible trend and automatic weekly/yearly
    seasonality — the strongest of the bundled options for longer web-evidence
    series. The worktree ``Prediction.ForecastEngine`` is imported lazily with
    ``ForecastConfig(model="prophet")``.

    Returns:
        An :class:`MlForecaster` whose engines fit Prophet models.

    Raises:
        PredictionError: At call time, when the worktree or prophet is missing.
    """

    def make_engine() -> _ForecastEngineLike:
        """Import the worktree engine and configure it for Prophet."""
        try:
            ensure_repo_on_path()
            from Prediction import ForecastConfig, ForecastEngine
        except ImportError as err:
            raise PredictionError(
                f"prophet forecaster needs the worktree engine: {err}; "
                "run `uv sync --extra forecast`"
            ) from err
        return ForecastEngine(ForecastConfig(model="prophet"))

    return MlForecaster(make_engine)


def to_forecast_frame(points: Sequence[EvidencePoint], *, metric: str = "web") -> object:
    """Convert evidence points into the ``ForecastEngine`` input frame.

    The worktree ``Prediction.ForecastEngine`` consumes frames with
    ``unique_id``, ``ds``, and ``y`` columns. pandas is imported lazily: it is
    part of the ``forecast`` extra, not a core dependency.

    Args:
        points: Deduplicated evidence points (one per date).
        metric: Series label used as ``unique_id``.

    Returns:
        A pandas DataFrame with ``unique_id`` (str), ``ds`` (datetime64), ``y`` (float).

    Raises:
        PredictionError: pandas is not installed (``uv sync --extra forecast``).
    """
    try:
        import pandas as pd
    except ImportError as err:
        raise PredictionError(
            "to_forecast_frame needs pandas: run `uv sync --extra forecast`"
        ) from err
    return pd.DataFrame(
        {
            "unique_id": [metric] * len(points),
            "ds": pd.to_datetime([point.date for point in points]),
            "y": [float(point.value) for point in points],
        }
    )


class PredictionFrame(Protocol):
    """Structural view of the prediction frame ``ForecastEngine.predict`` returns."""

    @property
    def columns(self) -> Iterable[str]: ...

    def itertuples(self, *, index: bool) -> Iterable[tuple]: ...


class _ForecastEngineLike(Protocol):
    """Structural view of the worktree forecast engine the adapter drives."""

    def fit(self, frame: object) -> _ForecastEngineLike: ...

    def predict(self, horizon: int, **kwargs: object) -> PredictionFrame: ...


class MlForecaster:
    """Forecaster adapter bridging web evidence into the worktree ``ForecastEngine``.

    Fits a fresh engine per call (evidence is small and stateless) and maps the
    prediction frame back to ``(date, value, value, value)`` tuples — the ML
    path returns point forecasts, so the intervals are zero-width rather than
    invented uncertainty.

    Args:
        engine_factory: Zero-argument callable returning an unfitted engine.
            Defaults to lazily importing ``Prediction.ForecastEngine``.
    """

    def __init__(self, engine_factory: Callable[[], _ForecastEngineLike] | None = None) -> None:
        self._engine_factory = engine_factory

    def __call__(
        self, points: Sequence[EvidencePoint], horizon: int
    ) -> list[tuple[date, float, float, float]]:
        """Fit on ``points`` and forecast ``horizon`` steps."""
        engine = self._make_engine()
        frame = to_forecast_frame(points)
        rows = _prediction_rows(engine.fit(frame).predict(horizon))
        return [(row_date, value, value, value) for row_date, value in rows[:horizon]]

    def _make_engine(self) -> _ForecastEngineLike:
        """Return a fresh engine from the factory (lazy worktree import by default)."""
        if self._engine_factory is not None:
            return self._engine_factory()
        try:
            ensure_repo_on_path()
            from Prediction import ForecastEngine
        except ImportError as err:
            raise PredictionError(
                f"ForecastEngine not importable: {err}; run `uv sync --extra forecast`"
            ) from err
        return ForecastEngine()


def _prediction_rows(raw: PredictionFrame) -> list[tuple[date, float]]:
    """Extract ``(date, value)`` pairs from the engine's prediction frame.

    The prediction column name depends on the configured model
    (``lightgbm``, ``prophet``, ...), so the last column wins.

    Raises:
        PredictionError: The frame has no ``ds`` column.
    """
    columns = list(raw.columns)
    if "ds" not in columns or not columns:
        raise PredictionError(f"prediction frame lacks a 'ds' column: {columns}")
    value_column = columns[-1]
    rows: list[tuple[date, float]] = []
    for row in raw.itertuples(index=False):
        row_dict = dict(zip(columns, row, strict=True))
        ds = row_dict["ds"]
        point_date = ds.date() if hasattr(ds, "date") else date.fromisoformat(str(ds)[:10])
        rows.append((point_date, float(row_dict[value_column])))
    rows.sort(key=lambda item: item[0])
    return rows
