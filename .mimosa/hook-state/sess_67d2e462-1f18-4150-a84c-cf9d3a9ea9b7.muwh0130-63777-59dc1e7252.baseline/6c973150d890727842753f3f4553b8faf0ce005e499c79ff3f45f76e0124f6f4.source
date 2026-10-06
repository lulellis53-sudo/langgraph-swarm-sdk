"""Forecasting engine: global LightGBM models via ``mlforecast``.

Input frames are long format with columns ``unique_id``, ``ds`` and ``y``. Install with
``uv sync --extra forecast``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

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
        lightgbm_params: Parameters passed only to LightGBM.
        random_forest_params: Parameters passed only to scikit-learn Random Forest.
        prophet_params: Parameters passed only to Prophet.
        exogenous_features: Numeric columns used as known-ahead regressors.
        lag_transforms: Optional ``mlforecast`` lag transforms keyed by lag index.
        step_size: Default CV step between windows; ``None`` uses ``horizon`` per call.
        model: ``"lightgbm"``, ``"sklearn-random-forest"`` or ``"prophet"``.
    """

    freq: str = "D"
    lags: tuple[int, ...] = (1, 7)
    date_features: tuple[str, ...] = ("dayofweek", "month")
    lightgbm_params: dict[str, Any] = field(default_factory=dict)
    random_forest_params: dict[str, Any] = field(default_factory=dict)
    prophet_params: dict[str, Any] = field(default_factory=dict)
    exogenous_features: tuple[str, ...] = ()
    lag_transforms: dict[int, list[Any]] | None = None
    step_size: int | None = None
    model: str = "lightgbm"


def _validate(df: pd.DataFrame, *, min_rows_per_series: int) -> None:
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ForecastError(f"missing columns: {missing}")
    if df.empty:
        raise ForecastError("input must contain at least one row")
    if df["unique_id"].isna().any():
        raise ForecastError("column 'unique_id' contains null values")
    if df["ds"].isna().any():
        raise ForecastError("column 'ds' contains NaT or NaN")
    if df["y"].isna().any():
        raise ForecastError("column 'y' contains NaN")
    if not pd.api.types.is_numeric_dtype(df["y"]):
        raise ForecastError("column 'y' must be numeric")
    if not np.isfinite(df["y"].to_numpy(dtype=float)).all():
        raise ForecastError("column 'y' contains infinite values")
    if df.duplicated(["unique_id", "ds"]).any():
        raise ForecastError("duplicate (unique_id, ds) rows")
    for uid, series in df.groupby("unique_id", sort=False):
        dates = pd.DatetimeIndex(series["ds"].sort_values())
        if not dates.is_monotonic_increasing:
            raise ForecastError(f"timestamps for series {uid!r} are not ordered")
    shortest = int(df.groupby("unique_id").size().min())
    if shortest < min_rows_per_series:
        raise ForecastError(f"need >= {min_rows_per_series} rows per series, got {shortest}")


class ForecastEngine:
    """Fit one global LightGBM model across series, then forecast or backtest."""

    def __init__(self, config: ForecastConfig | None = None) -> None:
        self.config = config or ForecastConfig()
        self._validate_config()
        self._forecaster = self._build()
        self._prophet_models: dict[Any, Any] = {}
        self._series_ids: set[Any] = set()
        self._last_timestamps: dict[Any, pd.Timestamp] = {}
        self._fitted = False

    def _validate_config(self) -> None:
        if not self.config.lags or any(lag < 1 for lag in self.config.lags):
            raise ForecastError("lags must contain positive integers")
        if len(set(self.config.lags)) != len(self.config.lags):
            raise ForecastError("lags must not contain duplicates")
        if self.config.step_size is not None and self.config.step_size < 1:
            raise ForecastError("step_size must be >= 1")
        if self.config.freq == "":
            raise ForecastError("freq must not be empty")
        if self.config.model not in {"lightgbm", "sklearn-random-forest", "prophet"}:
            raise ForecastError("model must be 'lightgbm', 'sklearn-random-forest' or 'prophet'")
        if self.config.lag_transforms is not None and any(
            lag < 1 for lag in self.config.lag_transforms
        ):
            raise ForecastError("lag_transforms keys must be positive integers")
        if self.config.model == "prophet" and self.config.lag_transforms:
            raise ForecastError("lag_transforms are not supported by Prophet")
        if len(set(self.config.exogenous_features)) != len(self.config.exogenous_features):
            raise ForecastError("exogenous_features must not contain duplicates")
        if set(self.config.exogenous_features) & set(REQUIRED_COLUMNS):
            raise ForecastError("exogenous_features cannot include required columns")

    def _build(self) -> Any:
        if self.config.model == "prophet":
            try:
                from prophet import Prophet  # noqa: F401
            except ImportError as exc:
                raise ForecastError("Install the 'forecast' extra to use Prophet") from exc
            self._model_key = "prophet"
            return None

        from mlforecast import MLForecast

        if self.config.model == "lightgbm":
            from lightgbm import LGBMRegressor

            params = {"n_estimators": 200, "verbosity": -1, "random_state": 0, "n_jobs": 1}
            params.update(self.config.lightgbm_params)
            estimator: Any = LGBMRegressor(**params)
        else:
            from sklearn.ensemble import RandomForestRegressor

            params = {"n_estimators": 200, "random_state": 0, "n_jobs": 1}
            params.update(self.config.random_forest_params)
            estimator = RandomForestRegressor(**params)
        model_key = "lgbm" if self.config.model == "lightgbm" else "random_forest"
        self._model_key = model_key
        kwargs: dict[str, Any] = {
            "models": {model_key: estimator},
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

    def min_rows_for_backtest(
        self,
        *,
        horizon: int,
        n_windows: int,
        step_size: int | None = None,
    ) -> int:
        """Minimum rows per series for rolling CV with the given window geometry."""
        step = (
            step_size
            if step_size is not None
            else (self.config.step_size if self.config.step_size is not None else horizon)
        )
        return self.min_rows_per_series + horizon + (n_windows - 1) * step

    def fit(self, df: Any) -> ForecastEngine:
        """Fit on a long-format frame; returns ``self``.

        Raises:
            ForecastError: On missing columns, NaN targets, duplicate keys or short series.
        """
        frame = self._to_pandas(df)
        _validate(frame, min_rows_per_series=self.min_rows_per_series)
        self._validate_features(frame, require_features=True)
        self._series_ids = set(frame["unique_id"].unique())
        self._last_timestamps = frame.groupby("unique_id")["ds"].max().to_dict()
        if self.config.model == "prophet":
            self._prophet_models = self._fit_prophet_models(frame)
        else:
            self._forecaster.fit(
                frame[[*REQUIRED_COLUMNS, *self.config.exogenous_features]], static_features=[]
            )
        self._fitted = True
        return self

    def predict(
        self, horizon: int, *, future_features: Any | None = None, output: str = "pandas"
    ) -> Any:
        """Forecast ``horizon`` steps for every fitted series.

        Returns:
            Frame with ``unique_id``, ``ds`` and the configured model prediction column.

        Raises:
            ForecastError: If the engine is unfitted or ``horizon`` is not positive.
        """
        if not self._fitted:
            raise ForecastError("fit() must be called before predict()")
        if horizon < 1:
            raise ForecastError("horizon must be >= 1")
        features = self._future_feature_frame(future_features, horizon)
        if self.config.model == "prophet":
            parts = []
            for uid, model in self._prophet_models.items():
                future = model.make_future_dataframe(
                    periods=horizon, freq=self.config.freq, include_history=False
                )
                if features is not None:
                    future = future.merge(
                        features.loc[
                            features["unique_id"] == uid, ["ds", *self.config.exogenous_features]
                        ],
                        on="ds",
                        how="left",
                        validate="one_to_one",
                    )
                forecast = model.predict(future)[["ds", "yhat"]].rename(columns={"yhat": "prophet"})
                forecast.insert(0, "unique_id", uid)
                parts.append(forecast)
            result = pd.concat(parts, ignore_index=True)
        else:
            result = self._forecaster.predict(horizon, X_df=features)
        return self._format_output(result, output)

    def _fit_prophet_models(self, frame: pd.DataFrame) -> dict[Any, Any]:
        from prophet import Prophet

        models = {}
        for uid, series in frame.groupby("unique_id", sort=False):
            model = Prophet(**self.config.prophet_params)
            for feature in self.config.exogenous_features:
                model.add_regressor(feature)
            model.fit(series[["ds", "y", *self.config.exogenous_features]])
            models[uid] = model
        return models

    def _validate_features(self, frame: pd.DataFrame, *, require_features: bool) -> None:
        missing = set(self.config.exogenous_features) - set(frame.columns)
        if missing:
            raise ForecastError(f"missing exogenous feature columns: {sorted(missing)}")
        if require_features and self.config.exogenous_features:
            features = frame[list(self.config.exogenous_features)]
            if not all(pd.api.types.is_numeric_dtype(features[col]) for col in features):
                raise ForecastError("exogenous features must be numeric")
            if features.isna().any().any() or not np.isfinite(features.to_numpy(dtype=float)).all():
                raise ForecastError("exogenous features must contain finite numeric values")

    def _future_feature_frame(
        self, future_features: Any | None, horizon: int
    ) -> pd.DataFrame | None:
        if not self.config.exogenous_features:
            if future_features is not None:
                raise ForecastError("future_features require configured exogenous_features")
            return None
        if future_features is None:
            raise ForecastError(
                "future_features are required when exogenous_features are configured"
            )
        frame = self._to_pandas(future_features)
        needed = {"unique_id", "ds", *self.config.exogenous_features}
        missing = needed - set(frame.columns)
        if missing:
            raise ForecastError(f"future_features missing columns: {sorted(missing)}")
        if frame.duplicated(["unique_id", "ds"]).any():
            raise ForecastError("duplicate (unique_id, ds) rows in future_features")
        if set(frame["unique_id"].unique()) != self._series_ids:
            raise ForecastError("future_features must cover exactly the fitted series")
        if len(frame) != horizon * len(self._series_ids):
            raise ForecastError("future_features must contain exactly horizon rows per series")
        for uid, rows in frame.groupby("unique_id"):
            expected = pd.date_range(
                start=self._last_timestamps[uid], periods=horizon + 1, freq=self.config.freq
            )[1:]
            actual = pd.DatetimeIndex(rows["ds"].sort_values())
            if not actual.equals(expected):
                raise ForecastError(f"future_features timestamps do not match freq for {uid!r}")
        self._validate_features(frame, require_features=True)
        return frame[["unique_id", "ds", *self.config.exogenous_features]]

    @staticmethod
    def _to_pandas(frame: Any) -> pd.DataFrame:
        if isinstance(frame, pd.DataFrame):
            return frame
        if frame.__class__.__module__.startswith("polars") and hasattr(frame, "to_dict"):
            return pd.DataFrame(frame.to_dict(as_series=False))
        if hasattr(frame, "to_pandas"):
            try:
                return frame.to_pandas()
            except ImportError as exc:
                raise ForecastError("PyArrow is required to convert this input to pandas") from exc
        raise ForecastError("input must be a pandas DataFrame or a Polars DataFrame")

    @classmethod
    def _format_output(cls, frame: pd.DataFrame, output: str) -> Any:
        if output == "pandas":
            return frame
        if output == "polars":
            return cls.to_polars(frame)
        if output == "arrow":
            return cls.to_arrow(frame)
        raise ForecastError("output must be 'pandas', 'polars' or 'arrow'")

    @staticmethod
    def to_polars(frame: pd.DataFrame) -> Any:
        """Convert a pandas result to Polars, loading Polars only when requested."""
        import polars as pl

        return pl.DataFrame(frame.to_dict(orient="list"))

    @staticmethod
    def to_arrow(frame: pd.DataFrame) -> Any:
        """Convert a pandas result to an Arrow table, loading PyArrow on demand."""
        import pyarrow as pa

        return pa.Table.from_pandas(frame, preserve_index=False)

    @staticmethod
    def metric_equations() -> dict[str, str]:
        """Return symbolic equations used by backtest metric calculation."""
        import sympy as sp

        n = sp.Symbol("n", positive=True, integer=True)
        i = sp.Symbol("i", integer=True, positive=True)
        y = sp.IndexedBase("y")
        yhat = sp.IndexedBase("y_hat")
        equations = {
            "mae": sp.Eq(sp.Symbol("MAE"), sp.Sum(sp.Abs(y[i] - yhat[i]), (i, 1, n)) / n),
            "rmse": sp.Eq(
                sp.Symbol("RMSE"),
                sp.sqrt(sp.Sum((y[i] - yhat[i]) ** 2, (i, 1, n)) / n),
            ),
            "smape": sp.Eq(
                sp.Symbol("sMAPE"),
                sp.Sum(
                    2 * sp.Abs(y[i] - yhat[i]) / (sp.Abs(y[i]) + sp.Abs(yhat[i])),
                    (i, 1, n),
                )
                / n,
            ),
        }
        return {name: sp.sstr(equation) for name, equation in equations.items()}

    def _prophet_backtest(
        self, frame: pd.DataFrame, *, horizon: int, n_windows: int, step_size: int
    ) -> pd.DataFrame:
        from prophet import Prophet

        rows = []
        for uid, series in frame.groupby("unique_id", sort=False):
            series = series.sort_values("ds")
            for window in range(n_windows):
                end = len(series) - horizon - (n_windows - 1 - window) * step_size
                train = series.iloc[:end]
                actual = series.iloc[end : end + horizon]
                model = Prophet(**self.config.prophet_params)
                for feature in self.config.exogenous_features:
                    model.add_regressor(feature)
                model.fit(train[["ds", "y", *self.config.exogenous_features]])
                predicted = model.predict(actual[["ds", *self.config.exogenous_features]])[
                    "yhat"
                ].to_numpy()
                rows.extend(
                    {"unique_id": uid, "y": y, "prophet": yhat}
                    for y, yhat in zip(actual["y"].to_numpy(), predicted, strict=True)
                )
        return pd.DataFrame(rows)

    def backtest(
        self,
        df: Any,
        *,
        horizon: int,
        n_windows: int = 3,
        step_size: int | None = None,
        output: str = "pandas",
    ) -> Any:
        """Rolling-origin cross-validation; returns per-series MAE, RMSE and sMAPE.

        ``step_size`` defaults to ``ForecastConfig.step_size`` or ``horizon`` when unset.

        Raises:
            ForecastError: On invalid data, ``horizon < 1`` or ``n_windows < 1``.
        """
        if horizon < 1 or n_windows < 1:
            raise ForecastError("horizon and n_windows must be >= 1")
        step = (
            step_size
            if step_size is not None
            else (self.config.step_size if self.config.step_size is not None else horizon)
        )
        if step < 1:
            raise ForecastError("step_size must be >= 1")
        frame = self._to_pandas(df)
        _validate(
            frame,
            min_rows_per_series=self.min_rows_for_backtest(
                horizon=horizon, n_windows=n_windows, step_size=step
            ),
        )
        self._validate_features(frame, require_features=True)
        if self.config.model == "prophet":
            cv = self._prophet_backtest(frame, horizon=horizon, n_windows=n_windows, step_size=step)
            prediction_column = "prophet"
        else:
            cv = self._forecaster.cross_validation(
                frame[[*REQUIRED_COLUMNS, *self.config.exogenous_features]],
                h=horizon,
                n_windows=n_windows,
                step_size=step,
                static_features=[],
            )
            prediction_column = self._model_key
        err = (cv["y"] - cv[prediction_column]).abs()
        cv = cv.assign(
            abs_err=err,
            sq_err=err**2,
            smape=2 * err / (cv["y"].abs() + cv[prediction_column].abs()).clip(lower=1e-9),
        )
        grouped = cv.groupby("unique_id")
        result = (
            grouped.agg(mae=("abs_err", "mean"), mse=("sq_err", "mean"), smape=("smape", "mean"))
            .assign(rmse=lambda f: f["mse"] ** 0.5)
            .drop(columns="mse")
            .reset_index()[["unique_id", "mae", "rmse", "smape"]]
        )
        return self._format_output(result, output)
