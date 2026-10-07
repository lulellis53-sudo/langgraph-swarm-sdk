"""Forecasting engine: global LightGBM models via ``mlforecast``.

Input frames are long format with columns ``unique_id``, ``ds`` and ``y``. Install with
``uv sync --extra forecast``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd
    from mlforecast import MLForecast

__all__ = ["ForecastConfig", "ForecastEngine", "ForecastError", "REQUIRED_COLUMNS"]

REQUIRED_COLUMNS = ("unique_id", "ds", "y")


class ForecastError(ValueError):
    """Raised for invalid input data or use of an unfitted engine."""


@dataclass(frozen=True, slots=True)
class ForecastConfig:
    """Model and feature settings.

    Attributes:
        freq: Pandas frequency alias of the series (``"D"``, ``"h"``, ...).
        lags: Target lags used as features.
        date_features: Calendar features derived from ``ds`` (pandas attribute names).
        lgbm_params: Extra ``lightgbm.LGBMRegressor`` keyword arguments.
        step_size: Advance between CV windows; ``None`` uses ``horizon`` (non-overlapping).
        lag_transforms: Optional ``mlforecast`` lag transforms keyed by lag index.
    """

    freq: str = "D"
    lags: tuple[int, ...] = (1, 7)
    date_features: tuple[str, ...] = ("dayofweek", "month")
    lgbm_params: dict[str, Any] = field(default_factory=dict)
    step_size: int | None = None
    lag_transforms: dict[int, list[Any]] | None = None


def _validate(df: pd.DataFrame, *, min_rows_per_series: int) -> None:
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
        self.config = config or ForecastConfig()
        self._forecaster = self._build()
        self._fitted = False

    def _build(self) -> MLForecast:
        from lightgbm import LGBMRegressor
        from mlforecast import MLForecast

        params: dict[str, Any] = {
            "n_estimators": 200,
            "verbosity": -1,
            "random_state": 0,
            "num_threads": 1,
        }
        params.update(self.config.lgbm_params)
        kwargs: dict[str, Any] = {
            "models": {"lgbm": LGBMRegressor(**params)},
            "freq": self.config.freq,
            "lags": list(self.config.lags),
            "date_features": list(self.config.date_features),
            "num_threads": 1,
        }
        if self.config.lag_transforms is not None:
            kwargs["lag_transforms"] = self.config.lag_transforms
        return MLForecast(**kwargs)

    @property
    def min_rows_per_series(self) -> int:
        """Smallest series length that leaves at least one training row after lagging."""
        return max(self.config.lags) + 1

    def min_rows_for_backtest(self, *, horizon: int, n_windows: int, step_size: int) -> int:
        """Minimum history per series for ``backtest`` with the given CV geometry.

        Needs lag warm-up plus ``n_windows`` validation blocks stepped by ``step_size``.
        """
        if horizon < 1 or n_windows < 1 or step_size < 1:
            raise ForecastError("horizon, n_windows, and step_size must be >= 1")
        return self.min_rows_per_series + horizon + (n_windows - 1) * step_size

    def fit(self, df: pd.DataFrame) -> ForecastEngine:
        """Fit on a long-format frame; returns ``self``.

        Raises:
            ForecastError: On missing columns, NaN targets, duplicate keys or short series.
        """
        _validate(df, min_rows_per_series=self.min_rows_per_series)
        self._forecaster.fit(df[list(REQUIRED_COLUMNS)])
        self._fitted = True
        return self

    def predict(self, horizon: int) -> pd.DataFrame:
        """Forecast ``horizon`` steps for every fitted series.

        Returns:
            Frame with ``unique_id``, ``ds`` and the ``lgbm`` prediction column.

        Raises:
            ForecastError: If the engine is unfitted or ``horizon`` is not positive.
        """
        if not self._fitted:
            raise ForecastError("fit() must be called before predict()")
        if horizon < 1:
            raise ForecastError("horizon must be >= 1")
        return self._forecaster.predict(horizon)

    def backtest(
        self,
        df: pd.DataFrame,
        *,
        horizon: int,
        n_windows: int = 3,
        step_size: int | None = None,
    ) -> pd.DataFrame:
        """Rolling-origin cross-validation; returns per-series MAE, RMSE and sMAPE.

        ``step_size`` defaults to ``horizon`` so validation windows do not overlap.

        Raises:
            ForecastError: On invalid data, ``horizon < 1`` or ``n_windows < 1``.
        """
        if horizon < 1 or n_windows < 1:
            raise ForecastError("horizon and n_windows must be >= 1")
        stride = step_size if step_size is not None else self.config.step_size
        stride = horizon if stride is None else stride
        if stride < 1:
            raise ForecastError("step_size must be >= 1")
        need = self.min_rows_for_backtest(horizon=horizon, n_windows=n_windows, step_size=stride)
        _validate(df, min_rows_per_series=need)
        cv = self._forecaster.cross_validation(
            df[list(REQUIRED_COLUMNS)],
            h=horizon,
            n_windows=n_windows,
            step_size=stride,
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
