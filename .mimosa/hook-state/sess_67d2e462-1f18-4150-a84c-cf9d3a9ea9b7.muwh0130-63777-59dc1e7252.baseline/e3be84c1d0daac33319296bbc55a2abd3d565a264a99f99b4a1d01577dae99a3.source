"""Lock the Benchmark.md statistical protocol: tails, ABBA, bootstrap, claims."""

from __future__ import annotations

import math
import random
import statistics

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from benchmark.protocol import (
    TAIL_MIN_N,
    abba,
    allows_speedup_claim,
    bootstrap_median_ci,
    nearest_rank,
    paired_deltas,
    rss_to_bytes,
    sample_durations,
    summarize,
)
from benchmark.Tasks.agent_suite.suite import TAIL_MIN_N as SUITE_TAIL_MIN_N

_HYP = settings(max_examples=40, deadline=None)
_DURATIONS = st.lists(
    st.floats(min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False),
    min_size=2,
    max_size=40,
)


def test_tail_floor_matches_the_agent_suite() -> None:
    assert TAIL_MIN_N == SUITE_TAIL_MIN_N == 100


def test_thirty_samples_do_not_support_a_stable_tail() -> None:
    samples = [float(value) for value in range(1, 31)]
    stats = summarize(samples)

    assert stats["n"] == 30
    assert stats["p50"] == statistics.median(samples)
    assert stats["median"] == stats["p50"]
    # ceil(0.95 * 30) - 1 == 28 -> 29. ceil(0.99 * 30) - 1 == 29 -> 30.
    assert stats["p95"] == 29.0
    assert stats["p99"] == 30.0
    assert stats["p95"] < max(samples)
    assert stats["tail_supported"] is False
    assert stats["mad"] >= 0.0


def test_summarize_rejects_a_single_or_non_finite_sample() -> None:
    with pytest.raises(ValueError, match="samples"):
        summarize([1.0])
    with pytest.raises(ValueError, match="finite"):
        summarize([1.0, math.nan])


def test_zero_mean_reports_zero_cv() -> None:
    stats = summarize([0.0, 0.0])
    assert stats["cv_pct"] == 0.0
    assert stats["mad"] == 0.0


@_HYP
@given(samples=_DURATIONS)
def test_summary_matches_median_and_nearest_rank(samples: list[float]) -> None:
    stats = summarize(samples)
    ordered = sorted(samples)
    count = len(ordered)

    assert stats["n"] == count
    assert stats["p50"] == statistics.median(ordered)
    assert stats["p95"] == ordered[math.ceil(0.95 * count) - 1]
    assert stats["p99"] == ordered[math.ceil(0.99 * count) - 1]
    assert stats["p95"] <= stats["p99"]
    assert stats["mad"] == statistics.median(abs(sample - stats["median"]) for sample in ordered)
    mean = statistics.fmean(ordered)
    expected_cv = 0.0 if mean == 0.0 else statistics.stdev(ordered) / mean * 100.0
    assert stats["cv_pct"] == expected_cv
    assert stats["tail_supported"] is (count >= TAIL_MIN_N)


def test_nearest_rank_rejects_an_empty_sample() -> None:
    with pytest.raises(ValueError, match="ordered"):
        nearest_rank([], 0.95)


def test_sample_durations_discards_warmup_and_uses_the_clock() -> None:
    calls: list[str] = []
    ticks = iter(range(0, 100_000, 1_000))

    def workload() -> None:
        calls.append("run")

    def clock_ns() -> int:
        return next(ticks)

    durations = sample_durations(workload, warmup=2, samples=3, clock_ns=clock_ns)

    assert calls == ["run"] * 5
    assert durations == [1_000, 1_000, 1_000]


def test_sample_durations_rejects_a_short_run_before_calling() -> None:
    def workload() -> None:
        raise AssertionError("must not run")

    with pytest.raises(ValueError, match="samples"):
        sample_durations(workload, warmup=-1, samples=2)
    with pytest.raises(ValueError, match="samples"):
        sample_durations(workload, samples=1)


def test_sample_durations_propagates_workload_errors() -> None:
    def workload() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        sample_durations(workload, warmup=0, samples=2)


def test_abba_keeps_each_variant_and_balances_slot_position() -> None:
    calls: list[str] = []

    def time_a() -> float:
        calls.append("A")
        return float(len(calls))

    def time_b() -> float:
        calls.append("B")
        return float(-len(calls))

    a_samples, b_samples = abba(time_a, time_b, rounds=2)

    assert calls == ["A", "B", "B", "A", "B", "A", "A", "B"]
    assert a_samples == [1.0, 4.0, 6.0, 7.0]
    assert b_samples == [-2.0, -3.0, -5.0, -8.0]
    a_positions = [index for index, label in enumerate(calls) if label == "A"]
    b_positions = [index for index, label in enumerate(calls) if label == "B"]
    assert sum(a_positions) == sum(b_positions)


def test_abba_rejects_zero_rounds() -> None:
    with pytest.raises(ValueError, match="rounds"):
        abba(lambda: 1.0, lambda: 2.0, rounds=0)


def test_paired_deltas_subtract_matched_samples() -> None:
    assert paired_deltas([5.0, 1.0], [2.0, 4.0]) == [3.0, -3.0]
    with pytest.raises(ValueError, match="paired"):
        paired_deltas([1.0], [1.0, 2.0])
    with pytest.raises(ValueError, match="paired"):
        paired_deltas([], [])


def test_bootstrap_median_interval_is_seeded_and_ordered() -> None:
    deltas = [10.0, 20.0, 30.0]
    low, high = bootstrap_median_ci(deltas, resamples=4, confidence=0.95, seed=0)

    assert (low, high) == (20.0, 30.0)
    assert bootstrap_median_ci(deltas, resamples=4, confidence=0.95, seed=0) == (low, high)
    assert low <= statistics.median(deltas) <= high

    rng = random.Random(0)
    drawn = sorted(statistics.median(rng.choices(deltas, k=len(deltas))) for _ in range(4))
    assert drawn == [20.0, 20.0, 20.0, 30.0]


def test_bootstrap_rejects_a_bad_interval_request() -> None:
    with pytest.raises(ValueError, match="deltas"):
        bootstrap_median_ci([1.0], resamples=4)
    with pytest.raises(ValueError, match="deltas"):
        bootstrap_median_ci([1.0, 2.0], resamples=0)
    with pytest.raises(ValueError, match="deltas"):
        bootstrap_median_ci([1.0, 2.0], confidence=1.0)
    with pytest.raises(ValueError, match="finite"):
        bootstrap_median_ci([1.0, math.inf])


@pytest.mark.parametrize(
    ("delta", "dispersion", "runs", "allowed"),
    [
        (10.0, 1.0, 1, False),
        (4.0, 2.0, 2, False),
        (4.01, 2.0, 2, True),
        (0.0, 0.0, 2, False),
        (1.0, 0.0, 2, True),
        (1.0, -0.1, 3, False),
    ],
)
def test_one_run_never_claims_a_speedup(
    delta: float,
    dispersion: float,
    runs: int,
    allowed: bool,
) -> None:
    assert (
        allows_speedup_claim(delta=delta, dispersion=dispersion, independent_runs=runs) is allowed
    )


def test_rss_unit_is_bytes_on_macos_and_kib_elsewhere() -> None:
    assert rss_to_bytes(4096, platform="darwin") == 4096
    assert rss_to_bytes(4, platform="linux") == 4096
    with pytest.raises(ValueError, match="ru_maxrss"):
        rss_to_bytes(-1, platform="darwin")
