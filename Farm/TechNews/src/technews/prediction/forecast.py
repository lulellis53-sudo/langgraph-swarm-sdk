"""Trend forecaster for news category volumes, wrapping ``Prediction.ForecastEngine``.

Degrades gracefully: without ``lightgbm``/``mlforecast`` (root dev extra), ``fit`` falls
back to a per-series linear trend (``numpy.polyfit`` on day-index) so the module stays
usable offline.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import pandas as pd
    from Modules.Prediction import ForecastConfig

__all__ = ["ForecastPoint", "TrendForecaster"]

logger = logging.getLogger(__name__)

_EXTRA = "forecast root dev extra (uv sync --extra forecast)"

_MIN_ROWS = 15  # engine needs max(lags)=7 + 1; require enough for a fallback trend too


@dataclass(frozen=True, slots=True)
class ForecastPoint:
    """One forecast value for one category."""

    category: str
    date: str  # ISO date
    yhat: float


class TrendForecaster:
    """Fit category volume series and forecast short-horizon trends."""

    def __init__(self, horizon: int = 7, config: ForecastConfig | None = None) -> None:
        if horizon < 1:
            raise ValueError("horizon must be >= 1")
        self.horizon = horizon
        self.config = config
        self._engine: object | None = None
        # cat -> (last_iso_date, last_y, slope)
        self._fallback_series: dict[str, tuple[str, float, float]] = {}
        self._fitted = False
        self._used_fallback = False

    @property
    def is_fitted(self) -> bool:
        """Whether ``fit`` has completed successfully."""
        return self._fitted

    def _fit_engine(self, frame: pd.DataFrame) -> bool:
        """Try to fit the LightGBM engine; return False if deps are missing."""
        try:
            from Modules.Prediction import ForecastEngine
        except ImportError as err:
            msg = f"Prediction package unavailable: {err}; install the {_EXTRA}"
            raise ImportError(msg) from err
        try:
            import lightgbm  # noqa: F401
            import mlforecast  # noqa: F401
        except ImportError as err:
            logger.info(
                "lightgbm/mlforecast unavailable (%s); falling back to linear trend", err
            )
            return False
        self._engine = ForecastEngine(self.config).fit(frame)
        return True

    def fit(self, frame: pd.DataFrame) -> None:
        """Validate and fit on a long frame (``unique_id``/``ds``/``y``).

        Raises:
            ForecastError: On invalid input (propagated from ``Prediction``).
            ValueError: On structural problems detected here.
        """

        missing = [c for c in ("unique_id", "ds", "y") if c not in frame.columns]
        if missing:
            raise ValueError(f"missing columns: {missing}")
        counts = frame["unique_id"].value_counts(sort=False)
        if len(counts) == 0 or int(counts.min()) < _MIN_ROWS:
            shortest = int(counts.min()) if len(counts) else 0
            raise ValueError(f"need >= {_MIN_ROWS} rows per series, got {shortest}")

        if self._fit_engine(frame):
            self._used_fallback = False
        else:
            self._fit_fallback(frame)
            self._used_fallback = True
        self._fitted = True

    def _fit_fallback(self, frame: pd.DataFrame) -> None:
        """Fit per-series linear trend on day-index; directly testable."""
        import pandas as pd

        self._fallback_series = {}
        for cat, group in frame.groupby("unique_id", observed=True):
            group = group.sort_values("ds")
            y = group["y"].to_numpy(dtype=float)
            dates = pd.to_datetime(group["ds"])
            day_index = (dates - dates.iloc[0]).dt.days.to_numpy(dtype=float)
            slope, intercept = np.polyfit(day_index, y, 1)
            self._fallback_series[str(cat)] = (
                dates.iloc[-1].date().isoformat(), float(y[-1]), float(slope)
            )

    def _linear_fallback_predict(self, cat: str, horizon: int) -> list[ForecastPoint]:
        """Extrapolate the fitted trend; directly testable."""
        last_iso, last_y, slope = self._fallback_series[cat]
        import datetime as _dt

        last = _dt.date.fromisoformat(last_iso)
        return [
            ForecastPoint(
                category=cat,
                date=(last + _dt.timedelta(days=h + 1)).isoformat(),
                yhat=max(0.0, last_y + slope * (h + 1)),
            )
            for h in range(horizon)
        ]

    def predict(self) -> list[ForecastPoint]:
        """Return the ``horizon``-day forecast per series, sorted by (category, date).

        Raises:
            RuntimeError: If called before ``fit``.
        """
        if not self._fitted:
            raise RuntimeError("fit() must be called before predict()")
        if self._used_fallback:
            points = [
                p
                for cat in self._fallback_series
                for p in self._linear_fallback_predict(cat, self.horizon)
            ]
        else:
            import pandas as pd

            out = self._engine.predict(self.horizon)  # type: ignore[attr-defined]
            records = out.rename(columns={"lgbm": "yhat"})
            points = [
                ForecastPoint(
                    category=str(r.unique_id),
                    date=pd.Timestamp(r.ds).date().isoformat(),
                    yhat=float(r.yhat),
                )
                for r in records.itertuples(index=False)
            ]
        return sorted(points, key=lambda p: (p.category, p.date))

    def movers(self, frame: pd.DataFrame) -> list[tuple[str, float]]:
        """Categories ranked by expected percent change of forecast mean vs last observed.

        Series whose last observed value is zero are skipped.
        """
        forecast = self.predict()
        if not forecast:
            return []

        last = frame.sort_values("ds").groupby("unique_id", observed=True)["y"].last()
        sums: dict[str, float] = {}
        counts: dict[str, int] = {}
        for p in forecast:
            sums[p.category] = sums.get(p.category, 0.0) + p.yhat
            counts[p.category] = counts.get(p.category, 0) + 1
        movers: list[tuple[str, float]] = []
        for cat, total in sums.items():
            base = float(last.get(cat, np.nan))
            if not np.isfinite(base) or base == 0.0:
                continue
            forecast_mean = total / counts[cat]
            movers.append((cat, (forecast_mean - base) / base * 100.0))
        movers.sort(key=lambda item: abs(item[1]), reverse=True)
        return movers
