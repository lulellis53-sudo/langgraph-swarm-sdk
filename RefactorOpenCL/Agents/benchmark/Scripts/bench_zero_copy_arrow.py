#!/usr/bin/env python3
"""Benchmark allocation patterns related to zero-copy columnar buffers.

Uses list copy vs ``memoryview`` over a pre-sized buffer as a lightweight stand-in
for PyArrow/Polars zero-copy sharing (no Arrow dependency required to run).
"""

from __future__ import annotations

import argparse
import json
import time
import tracemalloc
from typing import Any


def test_standard_copy_allocation(elements: int) -> float:
    """Allocate a Python list and duplicate it (copy semantics).

    Args:
        elements: List length.

    Returns:
        Elapsed milliseconds for allocate + copy.
    """
    t0 = time.perf_counter()
    data = [float(i) for i in range(elements)]
    _copied = list(data)
    return (time.perf_counter() - t0) * 1000.0


def test_zero_copy_allocation(elements: int) -> float:
    """Allocate backing storage once and take a buffer view (no list duplication).

    Args:
        elements: Drives buffer size (8 bytes per element in the synthetic layout).

    Returns:
        Elapsed milliseconds for allocate + view creation.
    """
    t0 = time.perf_counter()
    data = [float(i) for i in range(elements)]
    # View shares storage; real Arrow paths would share an underlying capsule instead.
    _view = memoryview(bytearray(len(data) * 8))
    return (time.perf_counter() - t0) * 1000.0


def run_zero_copy_benchmark(elements: int) -> dict[str, Any]:
    """Compare copy vs view allocation and report peak traced memory.

    Args:
        elements: Problem size passed to both micro-benchmarks.

    Returns:
        Timings, speedup ratio, and ``tracemalloc`` peak RSS for the run.
    """
    tracemalloc.start()

    copy_ms = test_standard_copy_allocation(elements)
    zero_copy_ms = test_zero_copy_allocation(elements)

    _, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    speedup = round(copy_ms / max(zero_copy_ms, 0.001), 2)

    return {
        "element_count": elements,
        "standard_copy_ms": round(copy_ms, 2),
        "zero_copy_ms": round(zero_copy_ms, 2),
        "speedup_factor": f"{speedup}x",
        "peak_memory_rss_bytes": peak_mem,
        "peak_memory_rss_mb": round(peak_mem / (1024 * 1024), 2),
    }


def main() -> None:
    """CLI entry: parse flags, run the benchmark, print JSON to stdout."""
    parser = argparse.ArgumentParser(description="Zero-copy allocation micro-benchmark")
    parser.add_argument("--elements", type=int, default=500_000, help="Array element count")
    args = parser.parse_args()

    report = run_zero_copy_benchmark(args.elements)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
