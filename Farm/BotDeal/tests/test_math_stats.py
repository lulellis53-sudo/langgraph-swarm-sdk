"""Tests for robust statistics helpers in swarm_sdk.math.stats."""

from __future__ import annotations

import pytest

from swarm_sdk.math.stats import rolling_mean, welford


def test_welford_matches_two_pass_stats() -> None:
    data = [1.0, 2.0, 3.0, 4.0, 5.0]
    result = welford(data)
    mean = sum(data) / len(data)
    var = sum((x - mean) ** 2 for x in data) / len(data)
    assert result["count"] == len(data)
    assert result["mean"] == pytest.approx(mean)
    assert result["variance"] == pytest.approx(var)


def test_welford_empty_returns_zeros() -> None:
    assert welford([]) == {"count": 0.0, "mean": 0.0, "variance": 0.0}


def test_welford_is_numerically_stable() -> None:
    # Large offset with small spread exercises catastrophic cancellation.
    data = [1e9 + i for i in range(1000)]
    result = welford(data)
    expected_mean = 1e9 + 499.5
    expected_var = (1000**2 - 1) / 12
    assert result["mean"] == pytest.approx(expected_mean, rel=1e-9)
    assert result["variance"] == pytest.approx(expected_var, rel=1e-3)


def test_rolling_mean_window_3() -> None:
    data = [1.0, 2.0, 3.0, 4.0, 5.0]
    got = rolling_mean(data, 3)
    assert got == [0.0, 0.0, 2.0, 3.0, 4.0]


def test_rolling_mean_min_periods() -> None:
    data = [1.0, 2.0, 3.0, 4.0]
    got = rolling_mean(data, 3, min_periods=1)
    assert got == [1.0, 1.5, 2.0, 3.0]


def test_rolling_mean_invalid_window_raises() -> None:
    with pytest.raises(ValueError, match="window"):
        rolling_mean([1.0, 2.0], 0)


def test_rolling_mean_invalid_min_periods_raises() -> None:
    with pytest.raises(ValueError, match="min_periods"):
        rolling_mean([1.0, 2.0, 3.0], 2, min_periods=3)
