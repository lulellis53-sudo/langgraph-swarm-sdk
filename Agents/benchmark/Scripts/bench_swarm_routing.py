#!/usr/bin/env python3
"""Benchmark SwarmSDK routing primitives: JevRouter safety gate + model-tier scoring.

Measures ``JevRouter.evaluate_noul`` and ``JevRouter.evaluate_score`` latency
for a complex vs a trivial task using the deterministic local fallback
(no endpoint, no API key) — no network, no model API calls. These are the same
primitives ``SwarmSDK`` uses for router/model-tier selection.

Run: ``uv run python Agents/benchmark/Scripts/bench_swarm_routing.py``
"""

from __future__ import annotations

import argparse
import statistics
import time
from typing import Any

from swarm_sdk.core.jev_router import JevRouter

COMPLEX_TASK = (
    "Refactor the streaming ingestion pipeline: split the batch window aggregator into "
    "stateless worker shards, add backpressure-aware retry with exponential jitter, "
    "migrate the checkpoint store to a write-ahead log, and keep the public API stable."
)
TRIVIAL_TASK = "Add a docstring to greet()."


def _offline_router() -> JevRouter:
    """Build a router pinned to the deterministic local fallback."""
    router = JevRouter()
    # Ensure no remote Jev endpoint is contacted, even if env vars are set.
    router.endpoint = None
    router.api_key = None
    return router


def _percentiles(samples_ms: list[float]) -> dict[str, float]:
    """Compute mean, p50, p95 and stdev for a list of latency samples (ms)."""
    ordered = sorted(samples_ms)
    idx95 = min(len(ordered) - 1, max(0, round(0.95 * (len(ordered) - 1))))
    idx50 = min(len(ordered) - 1, max(0, round(0.50 * (len(ordered) - 1))))
    return {
        "mean": statistics.fmean(ordered),
        "p50": ordered[idx50],
        "p95": ordered[idx95],
        "stdev": statistics.pstdev(ordered) if len(ordered) > 1 else 0.0,
    }


def _bench_callable(
    label: str, fn: Any, iterations: int, warmup: int
) -> dict[str, Any]:
    """Time one callable over N iterations and return a stats row.

    Args:
        label: Row label for the report.
        fn: Zero-argument callable to time (the router call is wrapped).
        iterations: Measured invocations.
        warmup: Unmeasured invocations discarded before timing.

    Returns:
        Report row with latency percentiles and a sample of the callable's verdict.
    """
    for _ in range(warmup):
        fn()
    samples_ms: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        fn()
        samples_ms.append((time.perf_counter() - t0) * 1000.0)
    stats = _percentiles(samples_ms)
    return {
        "label": label,
        "mean_ms": round(stats["mean"], 3),
        "p50_ms": round(stats["p50"], 3),
        "p95_ms": round(stats["p95"], 3),
        "stdev_ms": round(stats["stdev"], 3),
        "iterations": iterations,
    }


def run_routing_benchmark(iterations: int, warmup: int) -> dict[str, Any]:
    """Benchmark safety-gate and model-tier selection for both task profiles.

    Args:
        iterations: Measured router invocations per case.
        warmup: Unmeasured warmup invocations per case.

    Returns:
        Report with per-case stats plus the model tiers the router selected.
    """
    router = _offline_router()

    noul_complex = router.evaluate_noul(COMPLEX_TASK)
    noul_trivial = router.evaluate_noul(TRIVIAL_TASK)
    score_complex = router.evaluate_score(COMPLEX_TASK)
    score_trivial = router.evaluate_score(TRIVIAL_TASK)

    cases: list[tuple[str, Any]] = [
        ("noul(complex)", lambda: router.evaluate_noul(COMPLEX_TASK)),
        ("noul(trivial)", lambda: router.evaluate_noul(TRIVIAL_TASK)),
        ("score(complex)", lambda: router.evaluate_score(COMPLEX_TASK)),
        ("score(trivial)", lambda: router.evaluate_score(TRIVIAL_TASK)),
    ]
    rows = [
        _bench_callable(label, fn, iterations, warmup) for label, fn in cases
    ]

    return {
        "mode": "local fallback (endpoint=None)",
        "rows": rows,
        "noul_decision_complex": noul_complex.decision,
        "noul_decision_trivial": noul_trivial.decision,
        "model_tier_complex": score_complex.model_tier,
        "complexity_bucket_complex": score_complex.complexity_bucket,
        "model_tier_trivial": score_trivial.model_tier,
        "complexity_bucket_trivial": score_trivial.complexity_bucket,
    }


def main() -> None:
    """CLI entry: parse flags, run the benchmark, print a results table."""
    parser = argparse.ArgumentParser(description="JevRouter routing latency benchmark")
    parser.add_argument("--iterations", type=int, default=200, help="Measured run count per case")
    parser.add_argument("--warmup", type=int, default=20, help="Unmeasured warmup runs per case")
    args = parser.parse_args()

    report = run_routing_benchmark(args.iterations, args.warmup)

    print(f"JevRouter local routing latency — mode: {report['mode']}")
    header = (
        f"  {'case':18s} {'mean_ms':>9s} {'p50_ms':>9s} {'p95_ms':>9s}"
        f" {'stdev_ms':>9s} {'iters':>7s}"
    )
    print(header)
    for row in report["rows"]:
        print(
            f"  {row['label']:18s} {row['mean_ms']:9.3f} {row['p50_ms']:9.3f} "
            f"{row['p95_ms']:9.3f} {row['stdev_ms']:9.3f} {row['iterations']:7d}"
        )
    print("  selections:")
    print(f"    noul_decision(complex)={report['noul_decision_complex']}")
    print(f"    noul_decision(trivial)={report['noul_decision_trivial']}")
    print(
        f"    model_tier(complex)={report['model_tier_complex']} "
        f"(bucket={report['complexity_bucket_complex']})"
    )
    print(
        f"    model_tier(trivial)={report['model_tier_trivial']} "
        f"(bucket={report['complexity_bucket_trivial']})"
    )


if __name__ == "__main__":
    main()
