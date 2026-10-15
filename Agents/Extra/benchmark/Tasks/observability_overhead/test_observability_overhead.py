"""Tests for the observability-overhead benchmark harness."""

from __future__ import annotations

import math

from benchmark.Tasks.observability_overhead.benchmark_observability_overhead import (
    _build_operations,
)
from benchmark.Tasks.observability_overhead.benchmark_observability_overhead import (
    run as run_report,
)


def test_operations_verify_and_measured_paths_are_available() -> None:
    """Every built operation passes its instrumentation check; no-op deps stay optional."""
    for op in _build_operations():
        if op.available:
            op.verify()


def test_observability_overhead_report_measures_all_paths() -> None:
    """A quick run returns per-op ABBA verdicts and finite ns/call overheads, offline."""
    blocks = 2
    report = run_report(calls_per_slot=200, blocks=blocks)

    assert report["metadata"]["calls_per_slot"] == 200
    assert report["metadata"]["abba_blocks"] == blocks
    measured = [row for row in report["results"] if row["available"]]
    assert measured, "expected at least one measured operation"
    for row in measured:
        assert row["calls_per_slot"] == 200
        assert row["floor_slot_ms"]["n"] == 2 * blocks  # A slots per ABBA schedule
        assert row["op_slot_ms"]["n"] == 2 * blocks
        assert row["floor_slot_ms"]["median"] > 0
        assert row["op_slot_ms"]["median"] > 0
        assert row["overhead_ns_per_call"] == row["overhead_ns_per_call"]  # finite
        assert row["verdict"]["label"] in {
            "B_faster",
            "B_slower",
            "no_detectable_difference",
        }
        low, high = row["verdict"]["bootstrap_ci_ms"]
        assert low <= high


def test_overhead_entries_carry_expected_operation_names() -> None:
    """The report covers the shipped wrappers: metrics, tracing, usage, logging."""
    report = run_report(calls_per_slot=100, blocks=1)
    names = {row["operation"] for row in report["results"]}
    assert {
        "metrics_record_request",
        "tracing_noop_span",
        "usage_add",
        "logging_disabled_debug",
        "logging_nullhandler_info",
    } <= names


def test_overhead_ns_per_call_unit_conversion_is_exact() -> None:
    """ns/call x calls_per_slot / 1e6 must reproduce the paired median delta (float64)."""
    calls_per_slot, blocks = 250, 2
    report = run_report(calls_per_slot=calls_per_slot, blocks=blocks)
    for row in report["results"]:
        if not row["available"]:
            continue
        residual_ns = row["overhead_ns_per_call"] * calls_per_slot / 1e6
        assert math.isclose(residual_ns, row["verdict"]["median_delta_ms"], rel_tol=1e-12), row[
            "operation"
        ]


def run() -> None:
    """Entry point for ``python -m benchmark.run --task observability_overhead``."""
    from benchmark.Tasks.observability_overhead.benchmark_observability_overhead import main

    main(["--quick"])
