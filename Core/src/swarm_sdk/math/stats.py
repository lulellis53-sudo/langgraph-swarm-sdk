"""Robust online and rolling statistics for the math facade."""

from __future__ import annotations

from collections.abc import Sequence


def welford(data: Sequence[float | int]) -> dict[str, float]:
    """Return mean and population variance using Welford's online algorithm.

    The single-pass method is numerically stable and avoids the catastrophic
    cancellation of the naive ``sum((x - mean) ** 2)`` form.

    Args:
        data: Numeric sample. Empty input returns zeros.

    Returns:
        Mapping with ``count``, ``mean``, and ``variance``.
    """
    count = 0
    mean = 0.0
    m2 = 0.0
    for value in data:
        count += 1
        delta = float(value) - mean
        mean += delta / count
        delta2 = float(value) - mean
        m2 += delta * delta2
    if count == 0:
        return {"count": 0.0, "mean": 0.0, "variance": 0.0}
    return {"count": float(count), "mean": mean, "variance": m2 / count}


def rolling_mean(
    data: Sequence[float | int],
    window: int,
    *,
    min_periods: int | None = None,
) -> list[float]:
    """Return the simple rolling mean of ``data`` over ``window``.

    Uses PyArrow chunked compute when available, otherwise a sliding-window
    pure-Python implementation. ``min_periods`` defaults to ``window``; values
    before ``min_periods`` observations are present are ``0.0``.

    Args:
        data: Numeric series.
        window: Number of observations per window (>= 1).
        min_periods: Minimum observations to produce a non-zero value.

    Returns:
        Rolling mean with the same length as ``data``.
    """
    if window < 1:
        raise ValueError("window must be >= 1")
    if min_periods is None:
        min_periods = window
    if min_periods < 1 or min_periods > window:
        raise ValueError("min_periods must be in [1, window]")

    try:
        import pyarrow as pa  # type: ignore

        # pyarrow.compute does not have a native rolling mean; keep the Python
        # fallback now and leave a fast path for a future extension.
        del pa
        return _rolling_mean_python(data, window, min_periods)
    except ImportError:
        return _rolling_mean_python(data, window, min_periods)


def _rolling_mean_python(
    data: Sequence[float | int],
    window: int,
    min_periods: int,
) -> list[float]:
    """Compute the rolling mean without optional PyArrow."""
    out: list[float] = []
    total = 0.0
    values: list[float] = []
    for i, value in enumerate(data):
        values.append(float(value))
        total += float(value)
        if len(values) > window:
            total -= values.pop(0)
        if len(values) >= min_periods:
            out.append(total / len(values))
        else:
            out.append(0.0)
    return out


__all__ = ["rolling_mean", "welford"]
