"""Statistical protocol from ~/Desktop/Documentos/Benchmark.md.

Pure helpers for latency summaries, ABBA pairing, a percentile bootstrap
interval, and the two-run noise-floor gate. Nothing here times a workload
or writes a result file.
"""

from __future__ import annotations

import math
import random
import statistics
import time
from collections.abc import Callable
from typing import TypedDict

TAIL_MIN_N = 100
_NOISE_FLOOR_FACTOR = 2.0


class SampleSummary(TypedDict):
    """Dispersion report for one sample list, in the caller's unit."""

    n: int
    p50: float
    p95: float
    p99: float
    median: float
    mad: float
    mean: float
    stdev: float
    cv_pct: float
    tail_supported: bool


def nearest_rank(ordered: list[float], fraction: float) -> float:
    """Return the nearest-rank percentile of an ascending sample.

    Args:
        ordered: Samples sorted ascending.
        fraction: Percentile in ``(0, 1]``.

    Returns:
        The sample at ``ceil(fraction * n) - 1``.

    Raises:
        ValueError: When ``ordered`` is empty or ``fraction`` is out of range.
    """
    if not ordered or not 0.0 < fraction <= 1.0:
        raise ValueError("ordered must be non-empty and fraction must be in (0, 1]")
    index = math.ceil(fraction * len(ordered)) - 1
    return ordered[index]


def summarize(samples: list[float], *, tail_min_n: int = TAIL_MIN_N) -> SampleSummary:
    """Summarize durations with median, nearest-rank tails, MAD, and CV.

    Args:
        samples: At least two finite durations.
        tail_min_n: Smallest ``n`` that may support a P95/P99 claim.

    Returns:
        P50 as the median, nearest-rank P95 and P99, MAD, and CV percent.

    Raises:
        ValueError: When fewer than two finite samples are given.
    """
    if len(samples) < 2 or tail_min_n < 2:
        raise ValueError("samples must be at least 2 and tail_min_n must be at least 2")
    if any(not math.isfinite(sample) for sample in samples):
        raise ValueError("samples must be finite")
    ordered = sorted(samples)
    median = statistics.median(ordered)
    mean = statistics.fmean(ordered)
    stdev = statistics.stdev(ordered)
    count = len(ordered)
    return {
        "n": count,
        "p50": median,
        "p95": nearest_rank(ordered, 0.95),
        "p99": nearest_rank(ordered, 0.99),
        "median": median,
        "mad": statistics.median(abs(sample - median) for sample in ordered),
        "mean": mean,
        "stdev": stdev,
        "cv_pct": (stdev / mean * 100.0) if mean else 0.0,
        "tail_supported": count >= tail_min_n,
    }


def sample_durations(
    fn: Callable[[], object],
    *,
    warmup: int = 3,
    samples: int = 30,
    clock_ns: Callable[[], int] = time.perf_counter_ns,
) -> list[int]:
    """Time ``fn`` with a monotonic clock after discarded warmup calls.

    Args:
        fn: Workload. Its return value is ignored.
        warmup: Calls made before the first counted sample.
        samples: Counted repetitions. At least two.
        clock_ns: Nanosecond clock. Defaults to ``time.perf_counter_ns``.

    Returns:
        One non-negative nanosecond duration per counted call.

    Raises:
        ValueError: When ``warmup`` is negative or ``samples`` is below 2.
    """
    if warmup < 0 or samples < 2:
        raise ValueError("warmup must be non-negative and samples must be at least 2")
    for _ in range(warmup):
        fn()
    durations: list[int] = []
    for _ in range(samples):
        started = clock_ns()
        fn()
        durations.append(clock_ns() - started)
    return durations


def abba(
    time_a: Callable[[], float],
    time_b: Callable[[], float],
    *,
    rounds: int,
) -> tuple[list[float], list[float]]:
    """Collect paired samples on an ABBA cadence that swaps each round.

    Even rounds run A, B, B, A. Odd rounds run B, A, A, B. Samples stay with
    the variant that produced them, so the rotation does not swap the labels.

    Args:
        time_a: Timer for variant A. Called twice per round.
        time_b: Timer for variant B. Called twice per round.
        rounds: Number of four-step cadences. At least one.

    Returns:
        ``(a_samples, b_samples)``, each of length ``2 * rounds``.

    Raises:
        ValueError: When ``rounds`` is below 1.
    """
    if rounds < 1:
        raise ValueError("rounds must be at least 1")
    a_samples: list[float] = []
    b_samples: list[float] = []
    for index in range(rounds):
        order = ("a", "b", "b", "a") if index % 2 == 0 else ("b", "a", "a", "b")
        for label in order:
            if label == "a":
                a_samples.append(time_a())
            else:
                b_samples.append(time_b())
    return a_samples, b_samples


def paired_deltas(xs: list[float], ys: list[float]) -> list[float]:
    """Return ``x - y`` for matched samples.

    Args:
        xs: Samples from one variant.
        ys: Samples from the other variant, same length.

    Returns:
        One paired difference per index.

    Raises:
        ValueError: When the lists differ in length or are empty.
    """
    if len(xs) != len(ys) or not xs:
        raise ValueError("paired samples must have the same non-zero length")
    return [left - right for left, right in zip(xs, ys, strict=True)]


def bootstrap_median_ci(
    deltas: list[float],
    *,
    resamples: int = 10_000,
    confidence: float = 0.95,
    seed: int = 0,
) -> tuple[float, float]:
    """Return a percentile bootstrap interval for the median of paired deltas.

    Args:
        deltas: At least two finite paired differences.
        resamples: Bootstrap draws. At least one.
        confidence: Interval mass in ``(0, 1)``.
        seed: Seed for ``random.Random`` so the interval is reproducible.

    Returns:
        Inclusive low and high bounds of the resampled medians.

    Raises:
        ValueError: When deltas, resamples, or confidence are out of range.
    """
    if len(deltas) < 2 or resamples < 1 or not 0.0 < confidence < 1.0:
        raise ValueError("need at least 2 deltas, resamples at least 1, and confidence in (0, 1)")
    if any(not math.isfinite(delta) for delta in deltas):
        raise ValueError("deltas must be finite")
    rng = random.Random(seed)
    medians = sorted(
        statistics.median(rng.choices(deltas, k=len(deltas))) for _ in range(resamples)
    )
    tail = (1.0 - confidence) / 2.0
    low_index = math.floor(tail * resamples)
    high_index = min(resamples - 1, math.ceil((1.0 - tail) * resamples) - 1)
    return medians[low_index], medians[high_index]


def allows_speedup_claim(*, delta: float, dispersion: float, independent_runs: int) -> bool:
    """Allow a speedup claim only past twice the paired dispersion, twice.

    Args:
        delta: Median of the paired differences.
        dispersion: MAD (or other stated dispersion) of those differences.
        independent_runs: Separate sessions that reproduced the comparison.

    Returns:
        True when a second run exists and ``abs(delta)`` exceeds ``2 * dispersion``.
    """
    if (
        independent_runs < 2
        or dispersion < 0.0
        or not math.isfinite(delta)
        or not math.isfinite(dispersion)
    ):
        return False
    return abs(delta) > (_NOISE_FLOOR_FACTOR * dispersion)


def rss_to_bytes(ru_maxrss: int, *, platform: str) -> int:
    """Convert ``ru_maxrss`` to bytes.

    Args:
        ru_maxrss: Value from ``resource.getrusage``.
        platform: ``sys.platform``. macOS reports bytes; other POSIX hosts report KiB.

    Returns:
        Peak RSS in bytes.

    Raises:
        ValueError: When ``ru_maxrss`` is negative.
    """
    if ru_maxrss < 0:
        raise ValueError("ru_maxrss must be non-negative")
    if platform == "darwin":
        return ru_maxrss
    return ru_maxrss * 1024
