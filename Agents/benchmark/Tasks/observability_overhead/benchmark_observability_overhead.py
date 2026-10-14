"""Per-call overhead of the shipped observability wrappers against a no-op floor.

Offline and key-free. Each operation (Prometheus counters/histograms, OpenTelemetry
no-op and real SDK spans, ``UsageLog.add``, stdlib logging on the disabled and
NullHandler paths) is paired against an empty function via the ABBA protocol from
``benchmark.stats`` (Benchmark.md §2.6): A = ``calls_per_slot`` floor calls, B = the
same number of observed calls, ``A B B A`` per block. Reports overhead in ns/call
with the paired verdict; instrumentation correctness is verified before timing.
"""

from __future__ import annotations

import argparse
import json
import logging
import platform
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from benchmark.stats import Summary, abba_schedule, block_deltas, paired_verdict, summarize

_WARMUP = 3
_CALLS_PER_SLOT = 2_000
_BLOCKS = 12


@dataclass(frozen=True, slots=True)
class Operation:
    """One measured observability call with its correctness check."""

    name: str
    description: str
    fn: Callable[[], None]
    verify: Callable[[], None]
    available: bool = True
    unavailable_reason: str = ""


def _build_operations() -> list[Operation]:
    """Assemble the operation list, detecting optional packages at build time."""
    from swarm_sdk.observability import metrics, tracing
    from swarm_sdk.observability.usage import UsageLog

    ops: list[Operation] = []

    def verify_metrics_request() -> None:
        before = metrics_record_sample("swarm_requests_total", ("swarm", "false")) or 0.0
        metrics.record_request("swarm", False)
        after = metrics_record_sample("swarm_requests_total", ("swarm", "false"))
        if after is None or after - before < 1:
            raise AssertionError("swarm_requests_total did not increase")

    def verify_metrics_step() -> None:
        before = metrics_record_sample("swarm_step_latency_seconds_count", ("bench",)) or 0.0
        metrics.observe_step("bench", 0.001)
        after = metrics_record_sample("swarm_step_latency_seconds_count", ("bench",))
        if after is None or after - before < 1:
            raise AssertionError("swarm_step_latency_seconds_count did not increase")

    if metrics.ENABLED:
        ops.append(
            Operation(
                "metrics_record_request",
                "Prometheus swarm_requests_total counter .labels().inc()",
                lambda: metrics.record_request("swarm", False),
                verify_metrics_request,
            )
        )
        ops.append(
            Operation(
                "metrics_observe_step",
                "Prometheus swarm_step_latency_seconds histogram .labels().observe()",
                lambda: metrics.observe_step("bench", 0.001),
                verify_metrics_step,
            )
        )
    else:
        ops.append(
            Operation(
                "metrics_record_request",
                "unavailable: prometheus-client not installed",
                lambda: None,
                lambda: None,
                available=False,
                unavailable_reason="prometheus-client not installed",
            )
        )

    def verify_noop_span() -> None:
        with tracing.span("bench.op", mode="swarm"):
            pass

    ops.append(
        Operation(
            "tracing_noop_span",
            "swarm_sdk.observability.tracing.span without a configured provider",
            lambda: _with_span(tracing, "bench.op"),
            verify_noop_span,
        )
    )

    sdk_tracer = _local_sdk_tracer()
    if sdk_tracer is not None:
        ops.append(
            Operation(
                "tracing_sdk_span",
                "real OpenTelemetry span into a local InMemorySpanExporter",
                lambda: _start_sdk_span(sdk_tracer),
                lambda: _verify_sdk_tracer(sdk_tracer),
            )
        )
    else:
        ops.append(
            Operation(
                "tracing_sdk_span",
                "unavailable: opentelemetry-sdk not installed",
                lambda: None,
                lambda: None,
                available=False,
                unavailable_reason="opentelemetry-sdk not installed",
            )
        )

    def verify_usage_add() -> None:
        log = UsageLog()
        log.add("coder", 12, False, model="openai:gpt-4o-mini")
        rows = log.summary()
        if not rows or rows[0]["tokens"] != 12:
            raise AssertionError("UsageLog.add did not record the event")

    ops.append(
        Operation(
            "usage_add",
            "UsageLog.add (list append + cost estimate; summary() excluded)",
            lambda: UsageLog().add("coder", 12, False, model="openai:gpt-4o-mini"),
            verify_usage_add,
        )
    )

    disabled = logging.getLogger("swarm.benchmark.observability.disabled")
    disabled.setLevel(logging.WARNING)
    disabled.propagate = False
    enabled = logging.getLogger("swarm.benchmark.observability.enabled")
    enabled.setLevel(logging.DEBUG)
    enabled.propagate = False
    enabled.addHandler(logging.NullHandler())

    def verify_logging_disabled() -> None:
        if disabled.isEnabledFor(logging.DEBUG):
            raise AssertionError("disabled logger must filter DEBUG calls")

    def verify_logging_enabled() -> None:
        if not enabled.isEnabledFor(logging.INFO):
            raise AssertionError("enabled logger must pass INFO calls")

    ops.append(
        Operation(
            "logging_disabled_debug",
            "logger.debug on a WARNING-level logger (filtered before formatting)",
            lambda: disabled.debug("bench event %s", "payload-1"),
            verify_logging_disabled,
        )
    )
    ops.append(
        Operation(
            "logging_nullhandler_info",
            "logger.info at DEBUG level with only a NullHandler (record built, no I/O)",
            lambda: enabled.info("bench event %s", "payload-1"),
            verify_logging_enabled,
        )
    )
    return ops


def metrics_record_sample(name: str, labels: tuple[str, ...]) -> float | None:
    """Read one Prometheus sample; None when prometheus-client is absent."""
    try:
        from prometheus_client import REGISTRY
    except ImportError:
        return None
    return REGISTRY.get_sample_value(name, dict(zip(_LABEL_NAMES[name], labels)))


_LABEL_NAMES: dict[str, tuple[str, ...]] = {
    "swarm_requests_total": ("mode", "cached"),
    "swarm_step_latency_seconds_count": ("step",),
}


def _with_span(tracing_mod: Any, name: str) -> None:
    with tracing_mod.span(name, mode="swarm"):
        pass


def _local_sdk_tracer() -> Any | None:
    """Return a tracer into an in-memory exporter without touching the global provider."""
    try:
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_exporter import InMemorySpanExporter
    except ImportError:
        return None
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(InMemorySpanExporter()))
    return provider.get_tracer("swarm.benchmark.observability")


def _start_sdk_span(tracer: Any) -> None:
    with tracer.start_as_current_span("bench.op", attributes={"mode": "swarm"}):
        pass


def _verify_sdk_tracer(tracer: Any) -> None:
    span_obj = None
    with tracer.start_as_current_span("bench.verify") as active:
        span_obj = active
    if span_obj is None or not span_obj.get_span_context().is_valid:
        raise AssertionError("SDK tracer did not produce a valid span context")


def _measure(
    floor: Callable[[], None], fn: Callable[[], None], calls: int, blocks: int
) -> tuple[Summary, Summary, dict[str, Any]]:
    """ABBA ``floor`` (A) vs ``fn`` (B); return floor/op summaries plus the verdict."""

    def slot(variant: Callable[[], None]) -> float:
        start = time.perf_counter_ns()
        for _ in range(calls):
            variant()
        return (time.perf_counter_ns() - start) / 1e6

    for fn_once in (floor, fn):
        fn_once()
    records: list[tuple[str, float]] = []
    for variant in abba_schedule(blocks):
        body = floor if variant == "A" else fn
        records.append((variant, slot(body)))
    deltas = block_deltas(records)
    verdict = paired_verdict(deltas)
    floor_summary = summarize([v for label, v in records if label == "A"])
    op_summary = summarize([v for label, v in records if label == "B"])
    verdict_dict: dict[str, Any] = {
        "label": verdict.label,
        "median_delta_ms": verdict.median_delta,
        "noise_floor_ms": verdict.noise_floor,
        "bootstrap_ci_ms": [verdict.ci_low, verdict.ci_high],
    }
    return floor_summary, op_summary, verdict_dict, verdict.median_delta


def run(
    operations: list[str] | None = None,
    *,
    calls_per_slot: int = _CALLS_PER_SLOT,
    blocks: int = _BLOCKS,
) -> dict[str, Any]:
    """Run the full overhead report; every number is measured, none hardcoded."""

    def floor() -> None:
        pass

    results: list[dict[str, Any]] = []
    for op in _build_operations():
        if operations is not None and op.name not in operations:
            continue
        if not op.available:
            results.append(
                {
                    "operation": op.name,
                    "description": op.description,
                    "available": False,
                    "unavailable_reason": op.unavailable_reason,
                }
            )
            continue
        op.verify()
        floor_summary, op_summary, verdict, median_delta = _measure(
            floor, op.fn, calls_per_slot, blocks
        )
        results.append(
            {
                "operation": op.name,
                "description": op.description,
                "available": True,
                "calls_per_slot": calls_per_slot,
                "floor_slot_ms": asdict(floor_summary),
                "op_slot_ms": asdict(op_summary),
                "overhead_ns_per_call": median_delta * 1e6 / calls_per_slot,
                "verdict": verdict,
            }
        )
    return {
        "metadata": {
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "calls_per_slot": calls_per_slot,
            "abba_blocks": blocks,
            "floor": "empty function; overhead_ns_per_call = paired median delta vs floor",
        },
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    """Print the report (and optionally write it under the gitignored results/ tree)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operations", nargs="+", default=None, help="subset of operation names")
    parser.add_argument("--calls-per-slot", type=int, default=_CALLS_PER_SLOT)
    parser.add_argument("--blocks", type=int, default=_BLOCKS)
    parser.add_argument("--quick", action="store_true", help="smoke workload for tests/CI")
    parser.add_argument("--write-results", action="store_true")
    args = parser.parse_args(argv)
    if args.quick:
        calls_per_slot, blocks = 200, 2
    else:
        calls_per_slot, blocks = args.calls_per_slot, args.blocks
    report = run(args.operations, calls_per_slot=calls_per_slot, blocks=blocks)
    output = json.dumps(report, indent=2)
    if args.write_results:
        path = Path(__file__).resolve().parents[2] / "results" / "observability_overhead"
        path.mkdir(parents=True, exist_ok=True)
        target = path / "latest.json"
        target.write_text(output + "\n", encoding="utf-8")
        print(f"Wrote {target}")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
