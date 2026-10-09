"""Turn daily count rows into forecast-ready long frames.

Produces frames with the columns ``unique_id``, ``ds`` and ``y`` expected by
``Prediction.engine.ForecastEngine``. Pandas is imported lazily inside functions
(matching ``engine.py``) so importing this module never requires pandas.
"""

from typing import TYPE_CHECKING

from technews.prediction.store import DailyCount

if TYPE_CHECKING:
    import types

    import pandas as pd

__all__ = [
    "MIN_HISTORY",
    "FeatureError",
    "build_frame",
    "ready_series",
    "top_categories",
    "validate_frame",
]

MIN_HISTORY = 7
"""Rows per series required before forecasting."""

REQUIRED_COLUMNS = ("unique_id", "ds", "y")


class FeatureError(ValueError):
    """Raised for invalid input data or malformed frames."""


def _import_pandas() -> types.ModuleType:
    import pandas as pd

    return pd


def build_frame(counts: list[DailyCount]) -> pd.DataFrame:
    """Return a sorted long frame with ``unique_id``=category, ``ds``=date, ``y``=n.

    Raises:
        FeatureError: On empty input or malformed rows.
    """
    pd = _import_pandas()
    if not counts:
        raise FeatureError("counts must not be empty")
    frame = pd.DataFrame(
        {
            "unique_id": [row.category for row in counts],
            "ds": [pd.to_datetime(row.date) for row in counts],
            "y": [int(row.n) for row in counts],
        }
    )
    if frame["y"].hasnans:
        raise FeatureError("column 'y' contains NaN")
    if frame.duplicated(["unique_id", "ds"]).any():
        raise FeatureError("duplicate (unique_id, ds) rows")
    return frame.sort_values(["unique_id", "ds"], kind="stable").reset_index(drop=True)


def ready_series(frame: pd.DataFrame) -> list[str]:
    """Return unique_ids with at least ``MIN_HISTORY`` rows, sorted by unique_id."""
    counts = frame["unique_id"].value_counts(sort=False)
    return sorted(uid for uid, n in counts.items() if n >= MIN_HISTORY)


def top_categories(frame: pd.DataFrame, k: int = 10) -> list[str]:
    """Return the top ``k`` categories by total article count, descending."""
    totals = frame.groupby("unique_id", sort=False)["y"].sum()
    ordered = totals.sort_values(ascending=False, kind="stable")
    return list(ordered.head(k).index)


def validate_frame(frame: pd.DataFrame) -> None:
    """Validate frame shape/dtypes with ``ForecastEngine`` input semantics.

    Raises:
        FeatureError: On missing columns, wrong ``ds``/``y`` dtypes, NaN targets
            or duplicate ``(unique_id, ds)`` rows.
    """
    missing = [col for col in REQUIRED_COLUMNS if col not in frame.columns]
    if missing:
        raise FeatureError(f"missing columns: {missing}")
    import pandas as pd

    if not pd.api.types.is_datetime64_any_dtype(frame["ds"]):
        raise FeatureError("column 'ds' must be datetime-typed")
    if not pd.api.types.is_numeric_dtype(frame["y"]):
        raise FeatureError("column 'y' must be numeric")
    if frame["y"].hasnans:
        raise FeatureError("column 'y' contains NaN")
    if frame.duplicated(["unique_id", "ds"]).any():
        raise FeatureError("duplicate (unique_id, ds) rows")
