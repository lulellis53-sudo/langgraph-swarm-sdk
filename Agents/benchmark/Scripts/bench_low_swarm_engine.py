#!/usr/bin/env python3
"""Benchmark LowSwarmEngine.end-to-end latency (LangGraph state machine).

Measures ``engine.run`` wall-clock latency over N iterations using a fake
synthesizer and a fake test runner — no network, no model API calls. The
engine's ``profile=True`` metrics (wall/cpu time) are also collected.

Run: ``uv run python Agents/benchmark/Scripts/bench_low_swarm_engine.py``
"""

from __future__ import annotations

import argparse
import statistics
import time
from typing import Any

from swarm_sdk.orchestrator import LowSwarmEngine, SwarmState

TASK = "Create a calculator module with add and subtract functions"


def _fake_synthesizer(state: SwarmState) -> dict[str, str]:
    """Return deterministic, lifeguard-clean code for the target files."""
    files = state.get("target_files") or ["solution.py"]
    return {fname: "def run() -> str:\n    return 'ok'\n" for fname in files}


def _fake_test_runner(synthesized_code: dict[str, str]) -> bool:
    """Pretend the synthesized code passes tests (pure function, no I/O)."""
    return bool(synthesized_code)


def _build_engine() -> LowSwarmEngine:
    """Construct an offline engine wired to the fake synthesizer/test runner."""
    return LowSwarmEngine(
        custom_synthesizer=_fake_synthesizer,
        test_runner=_fake_test_runner,
    )


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


def run_engine_benchmark(iterations: int, warmup: int) -> dict[str, Any]:
    """Run the engine end-to-end and collect latency statistics.

    Args:
        iterations: Measured ``engine.run`` invocations.
        warmup: Unmeasured invocations discarded before timing.

    Returns:
        JSON-serializable report with latency percentiles and success status.
    """
    engine = _build_engine()

    for _ in range(warmup):
        engine.run(TASK, target_files=["calculator.py"])

    latencies_ms: list[float] = []
    profiled_wall_ms: list[float] = []
    profiled_cpu_ms: list[float] = []
    statuses: dict[str, int] = {}

    for _ in range(iterations):
        t0 = time.perf_counter()
        state = engine.run(TASK, target_files=["calculator.py"], profile=True)
        latencies_ms.append((time.perf_counter() - t0) * 1000.0)
        status = str(state.get("status", "unknown"))
        statuses[status] = statuses.get(status, 0) + 1
        metrics = state.get("metrics") or {}
        profiled_wall_ms.append(float(metrics.get("wall_clock_ms", 0.0)))
        profiled_cpu_ms.append(float(metrics.get("cpu_time_ms", 0.0)))

    stats = _percentiles(latencies_ms)
    return {
        "iterations": iterations,
        "warmup": warmup,
        "statuses": statuses,
        "run_ms_mean": round(stats["mean"], 3),
        "run_ms_p50": round(stats["p50"], 3),
        "run_ms_p95": round(stats["p95"], 3),
        "run_ms_stdev": round(stats["stdev"], 3),
        "engine_profile_wall_ms_mean": round(
            statistics.fmean(profiled_wall_ms) if profiled_wall_ms else 0.0, 3
        ),
        "engine_profile_cpu_ms_mean": round(
            statistics.fmean(profiled_cpu_ms) if profiled_cpu_ms else 0.0, 3
        ),
    }


def main() -> None:
    """CLI entry: parse flags, run the benchmark, print a results table."""
    parser = argparse.ArgumentParser(description="LowSwarmEngine end-to-end latency benchmark")
    parser.add_argument("--iterations", type=int, default=50, help="Measured run count")
    parser.add_argument("--warmup", type=int, default=5, help="Unmeasured warmup runs")
    args = parser.parse_args()

    report = run_engine_benchmark(args.iterations, args.warmup)

    print("LowSwarmEngine.run end-to-end latency (fake synthesizer/test runner, offline)")
    for key, value in report.items():
        print(f"  {key:32s} {value}")


if __name__ == "__main__":
    main()
