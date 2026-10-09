"""Offline tests for technews.prediction.features (no DB required)."""

from typing import Any

import pytest

from technews.prediction.features import (
    MIN_HISTORY,
    FeatureError,
    build_frame,
    ready_series,
    top_categories,
    validate_frame,
)
from technews.prediction.store import DailyCount


def _counts(spec: dict[str, int], days: int = 10) -> list[DailyCount]:
    """Build synthetic counts: each category gets ``days`` daily rows of size n."""
    return [
        DailyCount(date=f"2026-09-{d:02d}", category=cat, n=n)
        for cat, n in spec.items()
        for d in range(1, days + 1)
    ]


def _pandas() -> Any:
    pd = pytest.importorskip("pandas")
    return pd


def test_build_frame_empty_raises() -> None:
    with pytest.raises(FeatureError):
        build_frame([])


def test_build_frame_duplicate_keys_raise() -> None:
    _pandas()
    rows = _counts({"ai": 3}) + [DailyCount(date="2026-09-01", category="ai", n=5)]
    with pytest.raises(FeatureError, match="duplicate"):
        build_frame(rows)


def test_frame_construction_and_sorting() -> None:
    pd = _pandas()
    rows = [
        DailyCount(date="2026-09-02", category="ai", n=2),
        DailyCount(date="2026-09-01", category="web", n=7),
        DailyCount(date="2026-09-01", category="ai", n=1),
    ]
    frame = build_frame(rows)
    assert list(frame.columns) == ["unique_id", "ds", "y"]
    assert pd.api.types.is_datetime64_any_dtype(frame["ds"])
    assert frame["y"].tolist() == [1, 2, 7]  # sorted by (unique_id, ds)
    validate_frame(frame)


def test_ready_series_filters_short() -> None:
    _pandas()
    rows = _counts({"ai": 3}, days=MIN_HISTORY) + _counts({"short": 2}, days=MIN_HISTORY - 1)
    frame = build_frame(rows)
    assert ready_series(frame) == ["ai"]
    frame_short = build_frame(_counts({"tiny": 1}, days=MIN_HISTORY - 1))
    assert ready_series(frame_short) == []


def test_top_categories_ordering() -> None:
    _pandas()
    frame = build_frame(_counts({"ai": 5, "web": 9, "ops": 2}))
    assert top_categories(frame, 2) == ["web", "ai"]
    assert top_categories(frame) == ["web", "ai", "ops"]


def test_validate_missing_columns() -> None:
    pd = _pandas()
    with pytest.raises(FeatureError, match="missing columns"):
        validate_frame(pd.DataFrame({"unique_id": [], "ds": []}))


def test_validate_wrong_ds_dtype() -> None:
    pd = _pandas()
    frame = pd.DataFrame({"unique_id": ["a"], "ds": ["2026-09-01"], "y": [1]})
    with pytest.raises(FeatureError, match="datetime"):
        validate_frame(frame)


def test_validate_nan_y() -> None:
    pd = _pandas()
    frame = pd.DataFrame(
        {
            "unique_id": ["a", "b"],
            "ds": pd.to_datetime(["2026-09-01"] * 2),
            "y": [1.0, float("nan")],
        }
    )
    with pytest.raises(FeatureError, match="NaN"):
        validate_frame(frame)
