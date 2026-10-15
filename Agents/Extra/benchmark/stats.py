"""Robust statistics for benchmark observations (Benchmark.md §2.3 and §2.6).

Nearest-rank percentiles, MAD/IQR/CV dispersion, ABBA interleaving, paired deltas with a
bootstrap interval, and the noise-floor rule: a win must exceed twice the dispersion of the
paired deltas, exclude zero from its interval, and reproduce across independent sessions.
"""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Sequence
from dataclasses import dataclass

__all__ = [
    "TAIL_MIN_SAMPLES",
    "Summary",
    "Verdict",
    "abba_schedule",
    "block_deltas",
    "bootstrap_ci",
    "combine_sessions",
    "median_abs_deviation",
    "paired_verdict",
    "percentile",
    "summarize",
]

# Below this many independent observations P95/P99 are reported but flagged as unreliable.
TAIL_MIN_SAMPLES = 100
_NOISE_MULTIPLIER = 2.0


@dataclass(frozen=True, slots=True)
class Summary:
    """Distribution summary of one benchmark's observations (same unit as the input)."""

    n: int
    mean: float
    median: float
    mad: float
    iqr: float
    cv_pct: float
    min: float
    max: float
    p95: float
    p99: float
    tail_reliable: bool


@dataclass(frozen=True, slots=True)
class Verdict:
    """Outcome of a paired A/B comparison of per-block deltas (B minus A)."""

    label: str
    median_delta: float
    noise_floor: float
    ci_low: float
    ci_high: float


def _require(values: Sequence[float]) -> None:
    """Raise if ``values`` is empty."""
    if len(values) == 0:
        raise ValueError("empty sequence of observations")


def percentile(values: Sequence[float], q: float) -> float:
    """Return the nearest-rank percentile ``q`` (0 < q <= 100) of ``values``."""
    _require(values)
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100.0 * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def median_abs_deviation(values: Sequence[float]) -> float:
    """Return the median absolute deviation, which outliers barely move."""
    _require(values)
    centre = statistics.median(values)
    return statistics.median(abs(value - centre) for value in values)


def summarize(values: Sequence[float]) -> Summary:
    """Summarize ``values`` with robust and classical statistics.

    Raises:
        ValueError: If ``values`` is empty.
    """
    _require(values)
    n = len(values)
    mean = statistics.fmean(values)
    quartiles = statistics.quantiles(values, n=4, method="inclusive") if n > 1 else [0.0, 0.0, 0.0]
    stdev = statistics.stdev(values) if n > 1 else 0.0
    return Summary(
        n=n,
        mean=mean,
        median=statistics.median(values),
        mad=median_abs_deviation(values),
        iqr=quartiles[2] - quartiles[0],
        cv_pct=stdev / mean * 100.0 if mean else 0.0,
        min=min(values),
        max=max(values),
        p95=percentile(values, 95),
        p99=percentile(values, 99),
        tail_reliable=n >= TAIL_MIN_SAMPLES,
    )


def bootstrap_ci(
    values: Sequence[float], *, n_boot: int = 2000, alpha: float = 0.05, seed: int = 0
) -> tuple[float, float]:
    """Return a percentile-bootstrap ``1 - alpha`` interval for the median of ``values``."""
    _require(values)
    rng = random.Random(seed)
    n = len(values)
    medians = sorted(statistics.median(rng.choices(values, k=n)) for _ in range(n_boot))
    low = medians[int(alpha / 2 * n_boot)]
    high = medians[min(n_boot - 1, int((1 - alpha / 2) * n_boot))]
    return low, high


def abba_schedule(blocks: int) -> list[str]:
    """Return ``A B B A`` repeated ``blocks`` times; the order cancels linear drift."""
    return ["A", "B", "B", "A"] * blocks


def block_deltas(records: Sequence[tuple[str, float]]) -> list[float]:
    """Turn ordered ``(variant, value)`` records into one ``mean(B) - mean(A)`` per ABBA block.

    Raises:
        ValueError: If the record count is not a multiple of 4 or a block is not A,B,B,A.
    """
    if len(records) % 4 != 0:
        raise ValueError("records must come in blocks of 4 (a multiple of 4)")
    deltas: list[float] = []
    for start in range(0, len(records), 4):
        block = records[start : start + 4]
        if [variant for variant, _ in block] != ["A", "B", "B", "A"]:
            raise ValueError(f"block at {start} is not in A,B,B,A order")
        a_mean = (block[0][1] + block[3][1]) / 2.0
        b_mean = (block[1][1] + block[2][1]) / 2.0
        deltas.append(b_mean - a_mean)
    return deltas


def paired_verdict(deltas: Sequence[float], *, seed: int = 0) -> Verdict:
    """Judge per-block ``B - A`` deltas against the noise floor.

    A difference counts only when the median delta exceeds twice the deltas' MAD and the
    bootstrap interval excludes zero; otherwise the result is ``no_detectable_difference``.
    """
    median_delta = statistics.median(deltas)
    noise_floor = _NOISE_MULTIPLIER * median_abs_deviation(deltas)
    low, high = bootstrap_ci(deltas, seed=seed)
    label = "no_detectable_difference"
    if abs(median_delta) > noise_floor and (low > 0.0 or high < 0.0):
        label = "B_slower" if median_delta > 0 else "B_faster"
    return Verdict(label, median_delta, noise_floor, low, high)


def combine_sessions(labels: Sequence[str]) -> str:
    """Return the shared label if at least two independent sessions agree, else ``inconclusive``."""
    if len(labels) < 2 or len(set(labels)) != 1:
        return "inconclusive"
    return labels[0]
