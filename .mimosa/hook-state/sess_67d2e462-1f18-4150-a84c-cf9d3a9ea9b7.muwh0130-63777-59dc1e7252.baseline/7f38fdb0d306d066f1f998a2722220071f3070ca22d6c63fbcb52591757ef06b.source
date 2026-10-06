#!/usr/bin/env python3
"""Benchmark Python 3.15 free-threading (PEP 703) thread-pool scalability.

Measures wall-clock time and throughput for a CPU-bound workload across a
``ThreadPoolExecutor``. Compare runs with and without the GIL via
``sys._is_gil_enabled()`` when available.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any


def cpu_intensive_work(iterations: int) -> float:
    """Run a tight float loop so workers stay CPU-bound.

    Args:
        iterations: Inner loop bound; larger values increase per-task work.

    Returns:
        Accumulated trigonometric sum (discarded by callers; forces real math).
    """
    acc = 0.0
    for i in range(1, iterations + 1):
        acc += math.sin(i) * math.cos(i)
    return acc


def run_free_threading_benchmark(workers: int, tasks_per_worker: int) -> dict[str, Any]:
    """Execute parallel CPU work and report timing metadata.

    Args:
        workers: ``ThreadPoolExecutor`` worker count.
        tasks_per_worker: Tasks submitted per worker (total tasks = product).

    Returns:
        JSON-serializable metrics including GIL status and tasks per second.
    """
    # PEP 703 exposes this on free-threaded builds; standard builds always report True.
    gil_enabled = getattr(sys, "_is_gil_enabled", lambda: True)()
    total_tasks = workers * tasks_per_worker

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(cpu_intensive_work, 100_000) for _ in range(total_tasks)
        ]
        # Block until every task finishes so elapsed time includes tail latency.
        _ = [future.result() for future in futures]

    elapsed_s = time.perf_counter() - t0
    elapsed_ms = elapsed_s * 1000.0
    throughput = round(total_tasks / elapsed_s, 2) if elapsed_s > 0 else 0.0

    return {
        "gil_enabled": gil_enabled,
        "runtime_mode": (
            "GIL-Disabled (Free-Threaded)" if not gil_enabled else "GIL-Enabled (Standard)"
        ),
        "workers": workers,
        "total_tasks": total_tasks,
        "total_time_ms": round(elapsed_ms, 2),
        "tasks_per_sec": throughput,
    }


def main() -> None:
    """CLI entry: parse flags, run the benchmark, print JSON to stdout."""
    parser = argparse.ArgumentParser(description="Free-threading thread-pool benchmark")
    parser.add_argument("--workers", type=int, default=8, help="Worker thread count")
    parser.add_argument("--tasks", type=int, default=50, help="Tasks per worker")
    args = parser.parse_args()

    report = run_free_threading_benchmark(args.workers, args.tasks)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
