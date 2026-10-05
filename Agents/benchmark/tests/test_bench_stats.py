"""Robust statistics used by the benchmark protocol (Benchmark.md §2.3, §2.6)."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from benchmark.stats import (
    TAIL_MIN_SAMPLES,
    abba_schedule,
    block_deltas,
    bootstrap_ci,
    combine_sessions,
    paired_verdict,
    percentile,
    summarize,
)

_FLOATS = st.lists(
    st.floats(min_value=0.0, max_value=1e6, allow_nan=False), min_size=1, max_size=200
)


def test_percentile_is_nearest_rank() -> None:
    values = [15.0, 20.0, 35.0, 40.0, 50.0]
    assert percentile(values, 50) == 35.0
    assert percentile(values, 100) == 50.0
    assert percentile(values, 1) == 15.0


def test_thirty_samples_cannot_support_a_tail_estimate() -> None:
    """Benchmark.md §2.3: with 30 observations P99 is just the maximum and P95 the runner-up."""
    values = [float(i) for i in range(30)]
    assert percentile(values, 99) == max(values)
    assert percentile(values, 95) == 28.0
    assert summarize(values).tail_reliable is False


@given(_FLOATS)
def test_percentiles_are_ordered_and_bounded(values: list[float]) -> None:
    p50, p95, p99 = (percentile(values, q) for q in (50, 95, 99))
    assert min(values) <= p50 <= p95 <= p99 <= max(values)


def test_summary_of_known_values() -> None:
    summary = summarize([10.0, 12.0, 11.0, 13.0, 100.0])
    assert summary.n == 5
    assert summary.median == 12.0
    assert summary.mad == 1.0  # robust to the 100.0 outlier
    assert summary.min == 10.0
    assert summary.max == 100.0
    assert summary.mean > summary.median  # the outlier drags the mean, not the median


def test_summary_marks_tail_reliability_by_sample_count() -> None:
    assert summarize([1.0] * TAIL_MIN_SAMPLES).tail_reliable is True
    assert summarize([1.0] * (TAIL_MIN_SAMPLES - 1)).tail_reliable is False


@pytest.mark.parametrize("bad", [[], ()])
def test_empty_input_raises(bad: list[float]) -> None:
    with pytest.raises(ValueError, match="empty"):
        summarize(bad)
    with pytest.raises(ValueError, match="empty"):
        percentile(bad, 50)


def test_constant_values_have_zero_dispersion() -> None:
    summary = summarize([5.0] * 10)
    assert (summary.mad, summary.iqr, summary.cv_pct) == (0.0, 0.0, 0.0)


def test_bootstrap_ci_is_deterministic_and_contains_the_median() -> None:
    values = [1.0, 2.0, 2.5, 3.0, 4.0, 9.0, 2.2, 2.8]
    first = bootstrap_ci(values, seed=1)
    second = bootstrap_ci(values, seed=1)
    assert first == second
    low, high = first
    assert low <= 2.65 <= high


def test_abba_schedule_is_balanced_and_cancels_linear_drift() -> None:
    schedule = abba_schedule(3)
    assert schedule == ["A", "B", "B", "A"] * 3
    assert schedule.count("A") == schedule.count("B") == 6
    positions_a = [i for i, v in enumerate(schedule) if v == "A"]
    positions_b = [i for i, v in enumerate(schedule) if v == "B"]
    assert sum(positions_a) == sum(positions_b)  # same mean position: drift cancels


def test_block_deltas_pair_each_abba_block() -> None:
    records = [
        ("A", 10.0),
        ("B", 14.0),
        ("B", 16.0),
        ("A", 12.0),
        ("A", 20.0),
        ("B", 22.0),
        ("B", 24.0),
        ("A", 22.0),
    ]
    assert block_deltas(records) == [4.0, 2.0]  # (B mean) - (A mean) per block


def test_block_deltas_reject_incomplete_blocks() -> None:
    with pytest.raises(ValueError, match="multiple of 4"):
        block_deltas([("A", 1.0), ("B", 2.0)])


def test_verdict_needs_effect_above_noise_and_ci_excluding_zero() -> None:
    slower = paired_verdict([5.0, 5.1, 4.9, 5.2, 5.0, 4.8, 5.1, 5.0], seed=0)
    assert slower.label == "B_slower"
    noise = paired_verdict([0.5, -0.6, 0.4, -0.5, 0.6, -0.4, 0.5, -0.6], seed=0)
    assert noise.label == "no_detectable_difference"
    faster = paired_verdict([-5.0, -5.1, -4.9, -5.2, -5.0, -4.8, -5.1, -5.0], seed=0)
    assert faster.label == "B_faster"


def test_sessions_must_agree_to_claim_a_win() -> None:
    assert combine_sessions(["B_slower", "B_slower"]) == "B_slower"
    assert combine_sessions(["B_slower", "no_detectable_difference"]) == "inconclusive"
    assert combine_sessions(["B_slower", "B_faster"]) == "inconclusive"
    assert combine_sessions(["no_detectable_difference"] * 2) == "no_detectable_difference"
    assert combine_sessions(["B_slower"]) == "inconclusive"  # one run never reproduces
