#!/usr/bin/env python3
"""Benchmark Prometheus and OpenTelemetry recording overhead.

Measures wall time to record histogram/counter samples and to create short-lived
spans. Optional dependencies are probed at import time so the script still runs
when only one stack is installed.
"""

from __future__ import annotations

import argparse
import json
import time
from typing import Any

PROMETHEUS_AVAILABLE = False
OPENTELEMETRY_AVAILABLE = False

try:
    from prometheus_client import CollectorRegistry, Counter, Histogram

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

try:
    from opentelemetry import trace

    OPENTELEMETRY_AVAILABLE = True
except ImportError:
    OPENTELEMETRY_AVAILABLE = False


def run_telemetry_benchmark(iterations: int) -> dict[str, Any]:
    """Record metrics and spans in a tight loop and return timings.

    Args:
        iterations: Number of observe/inc and span cycles per backend.

    Returns:
        Per-backend availability flags and elapsed milliseconds (0 when absent).
    """
    t0 = time.perf_counter()

    if PROMETHEUS_AVAILABLE:
        registry = CollectorRegistry()
        hist = Histogram("test_lat", "Test Latency", registry=registry)
        counter = Counter("test_cnt", "Test Counter", registry=registry)
        for _ in range(iterations):
            hist.observe(0.005)
            counter.inc()

    prom_ms = (time.perf_counter() - t0) * 1000.0

    t1 = time.perf_counter()
    if OPENTELEMETRY_AVAILABLE:
        tracer = trace.get_tracer_provider().get_tracer("bench.tracer")
        for _ in range(iterations):
            with tracer.start_as_current_span("bench_span") as span:
                span.set_attribute("iter", 1)

    otel_ms = (time.perf_counter() - t1) * 1000.0

    return {
        "iterations": iterations,
        "prometheus_available": PROMETHEUS_AVAILABLE,
        "prometheus_export_ms": round(prom_ms, 2),
        "opentelemetry_available": OPENTELEMETRY_AVAILABLE,
        "opentelemetry_span_ms": round(otel_ms, 2),
    }


def main() -> None:
    """CLI entry: parse flags, run the benchmark, print JSON to stdout."""
    parser = argparse.ArgumentParser(description="Prometheus and OpenTelemetry benchmark")
    parser.add_argument("--iterations", type=int, default=1000, help="Iteration count")
    args = parser.parse_args()

    report = run_telemetry_benchmark(args.iterations)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
