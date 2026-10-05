"""Scripted solo and parallel bench of every loaded agent task.

Latency is WorkerAgent dispatch with a replayed reply. It is not provider
latency. The clock, warmup, median, nearest-rank tail, MAD, CV, and macOS RSS
rules follow ~/Documentos/Benchmark.md. One run never claims a speedup.

    PYTHONPATH=Agents uv run python -m benchmark.run --task agent_suite
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import platform
import statistics
import sys
import time
import tracemalloc
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from benchmark.Tasks.agent_suite.instruments import (
    SuiteInstruments,
    gc_collections,
    python_rss_bytes,
    rusage_delta,
    rusage_snapshot,
)
from benchmark.tests.fakes import Script, ScriptedModel, answer

from swarm_sdk.agents.manifest import AgentManifest, load_all_agent_manifests
from swarm_sdk.models.selection import bounded_gather
from swarm_sdk.orchestrator.worker import WorkerAgent

AGENTS_ROOT = Path(__file__).resolve().parents[3]
RESULTS_PATH = Path(__file__).resolve().parents[2] / "results" / "agent_suite" / "latest.json"
PARALLEL_CAP = 3
CLI_WARMUP = 1
CLI_SAMPLES = 30
TAIL_MIN_N = 100
SCRIPTED_REPLY = "done-ok"
_SCRIPTED_KEY = "scripted-bench"


class Distribution(TypedDict):
    n: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    median_ms: float
    mad_ms: float
    mean_ms: float
    stdev_ms: float
    cv_pct: float
    tail_supported: bool


class StepReport(TypedDict):
    agent: str
    task_id: str
    n: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    mad_ms: float
    cv_pct: float
    prompt_tokens_p50: float
    ok: int
    blocked: int
    error: int


class ModeReport(TypedDict):
    n: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    median_ms: float
    mad_ms: float
    mean_ms: float
    stdev_ms: float
    cv_pct: float
    tail_supported: bool
    peak_in_flight: int
    samples_ms: list[float]
    steps: list[StepReport]


class SuiteReport(TypedDict):
    task: str
    measured_at: str
    latency_kind: str
    command: str
    protocol: dict[str, object]
    env: dict[str, object]
    catalog: dict[str, object]
    modes: dict[str, ModeReport]
    comparison: dict[str, object]
    peak_rss_bytes: int
    rss_unit: str
    instruments: dict[str, object]
    failures: list[str]


@dataclass(frozen=True, slots=True)
class AgentStep:
    """One declared task on one loaded agent."""

    agent: str
    task_id: str
    description: str


@dataclass(frozen=True, slots=True)
class PassTiming:
    """One catalog pass."""

    wall_ns: int
    cpu_ns: int
    records: list[StepRecord]
    peak_in_flight: int


@dataclass(frozen=True, slots=True)
class StepRecord:
    """One execution of an agent task."""

    agent: str
    task_id: str
    status: str
    elapsed_ns: int
    prompt_tokens: int
    detail: str


class _Flight:
    """In-flight counter. Touched only on the event-loop thread."""

    def __init__(self) -> None:
        self.current = 0
        self.peak = 0

    def enter(self) -> None:
        self.current += 1
        self.peak = max(self.peak, self.current)

    def leave(self) -> None:
        self.current -= 1


def catalog(manifests: Mapping[str, AgentManifest]) -> list[AgentStep]:
    """Return every loaded agent's declared tasks, in agent-name order.

    An agent with an empty task list still contributes one step so the persona
    is exercised. Nested folders the loader skips stay out of the catalog.
    """
    steps: list[AgentStep] = []
    for name in sorted(manifests):
        manifest = manifests[name]
        if not manifest.tasks:
            steps.append(AgentStep(name, "", manifest.role))
            continue
        steps.extend(AgentStep(name, task.id, task.description) for task in manifest.tasks)
    return steps


def latency_distribution(samples_ms: list[float]) -> Distribution:
    """Summarize samples with the Benchmark.md median, nearest-rank, MAD, and CV.

    Args:
        samples_ms: At least two durations, in milliseconds.

    Returns:
        Median as P50, nearest-rank P95 and P99, MAD, and CV percent.

    Raises:
        ValueError: When fewer than two samples are given.
    """
    if len(samples_ms) < 2:
        raise ValueError("samples must be at least 2")
    ordered = sorted(samples_ms)
    median = statistics.median(ordered)
    deviations = [abs(sample - median) for sample in ordered]
    mean = statistics.fmean(ordered)
    stdev = statistics.stdev(ordered)
    n = len(ordered)
    return {
        "n": n,
        "p50_ms": median,
        "p95_ms": _nearest_rank(ordered, 0.95),
        "p99_ms": _nearest_rank(ordered, 0.99),
        "median_ms": median,
        "mad_ms": statistics.median(deviations),
        "mean_ms": mean,
        "stdev_ms": stdev,
        "cv_pct": (stdev / mean * 100.0) if mean else 0.0,
        "tail_supported": n >= TAIL_MIN_N,
    }


def _nearest_rank(ordered: list[float], fraction: float) -> float:
    index = math.ceil(fraction * len(ordered)) - 1
    return ordered[index]


def _environment() -> dict[str, object]:
    page = os.sysconf("SC_PAGE_SIZE")
    pages = os.sysconf("SC_PHYS_PAGES")
    gil = sys._is_gil_enabled() if hasattr(sys, "_is_gil_enabled") else True
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "ram_bytes": int(page) * int(pages),
        "python": platform.python_version(),
        "gil_enabled": gil,
    }


def _peak_rss_bytes() -> int:
    # macOS reports bytes. Linux reports KiB. Converted in python_rss_bytes.
    return python_rss_bytes()


@contextmanager
def _scripted_keys(manifests: Mapping[str, AgentManifest]) -> Iterator[None]:
    """Set missing provider env names so the worker does not open the keychain.

    The scripted model never reads the value. Names that were already set are
    left alone, and every name this function inserts is removed on exit.
    """
    names: set[str] = set()
    for manifest in manifests.values():
        if manifest.api_key_env:
            names.add(manifest.api_key_env)
        model = manifest.model or ""
        provider, separator, _model_id = model.partition(":")
        if separator and provider and provider != "inherit":
            names.add(f"{provider.upper()}_API_KEY")
    previous = {name: os.environ.get(name) for name in names}
    for name, value in previous.items():
        if not value:
            os.environ[name] = _SCRIPTED_KEY
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


async def _run_step(
    step: AgentStep,
    manifests: Mapping[str, AgentManifest],
    agents_root: str,
    flight: _Flight,
    *,
    mode: str,
    instruments: SuiteInstruments | None,
) -> StepRecord:
    manifest = manifests[step.agent]
    model: ScriptedModel
    if instruments is None:
        model = ScriptedModel(script=Script([answer(SCRIPTED_REPLY)]))
    else:
        model = instruments.make_model(manifest.model or "scripted", SCRIPTED_REPLY)
    worker = WorkerAgent(
        manifest,
        agents_root=agents_root,
        cache=None,
        model_override=model,
    )
    span = (
        instruments.span(
            "agent_suite.step",
            mode=mode,
            agent=step.agent,
            task_id=step.task_id or "role",
        )
        if instruments is not None
        else _idle_span()
    )
    flight.enter()
    started = time.perf_counter_ns()
    try:
        with span as active:
            try:
                output = await worker.run(
                    f"{step.agent}:{step.task_id or 'role'}",
                    step.description,
                    {},
                    task=step.task_id,
                )
            except Exception as exc:
                elapsed = time.perf_counter_ns() - started
                detail = f"{type(exc).__name__}: {exc}"
                record = StepRecord(step.agent, step.task_id, "error", elapsed, 0, detail[:180])
            else:
                elapsed = time.perf_counter_ns() - started
                detail = "; ".join(output.handoff_errors)
                record = StepRecord(
                    step.agent,
                    step.task_id,
                    output.status,
                    elapsed,
                    output.prompt_tokens,
                    detail[:180],
                )
            if active is not None:
                active.set_attribute("status", record.status)
            if instruments is not None:
                instruments.observe_step(
                    mode, record.status, record.elapsed_ns, record.prompt_tokens
                )
            return record
    finally:
        flight.leave()


@contextmanager
def _idle_span() -> Iterator[None]:
    yield None


async def _pass(
    steps: list[AgentStep],
    manifests: Mapping[str, AgentManifest],
    agents_root: str,
    *,
    parallel: bool,
    parallel_cap: int,
    instruments: SuiteInstruments | None,
) -> PassTiming:
    mode = "parallel" if parallel else "solo"
    flight = _Flight()
    span = (
        instruments.span("agent_suite.pass", mode=mode) if instruments is not None else _idle_span()
    )
    cpu_started = time.process_time_ns()
    started = time.perf_counter_ns()
    with span:
        if parallel:
            factories = [
                (
                    lambda step=step: _run_step(
                        step,
                        manifests,
                        agents_root,
                        flight,
                        mode=mode,
                        instruments=instruments,
                    )
                )
                for step in steps
            ]
            records = await bounded_gather(factories, max_concurrency=parallel_cap)
        else:
            records = []
            for step in steps:
                records.append(
                    await _run_step(
                        step,
                        manifests,
                        agents_root,
                        flight,
                        mode=mode,
                        instruments=instruments,
                    )
                )
    if instruments is not None:
        instruments.set_in_flight(mode, flight.peak)
    return PassTiming(
        wall_ns=time.perf_counter_ns() - started,
        cpu_ns=time.process_time_ns() - cpu_started,
        records=list(records),
        peak_in_flight=flight.peak,
    )


def _failures(records: list[StepRecord]) -> list[str]:
    return [
        f"{record.agent}:{record.task_id or 'role'} {record.status} {record.detail}".rstrip()
        for record in records
        if record.status != "ok"
    ]


def _step_reports(samples: list[list[StepRecord]], order: list[AgentStep]) -> list[StepReport]:
    grouped: dict[tuple[str, str], list[StepRecord]] = {}
    for records in samples:
        for record in records:
            grouped.setdefault((record.agent, record.task_id), []).append(record)
    reports: list[StepReport] = []
    for step in order:
        records = grouped.get((step.agent, step.task_id), [])
        durations = [record.elapsed_ns / 1e6 for record in records]
        stats = latency_distribution(durations)
        tokens = sorted(record.prompt_tokens for record in records)
        reports.append(
            {
                "agent": step.agent,
                "task_id": step.task_id,
                "n": stats["n"],
                "p50_ms": stats["p50_ms"],
                "p95_ms": stats["p95_ms"],
                "p99_ms": stats["p99_ms"],
                "mad_ms": stats["mad_ms"],
                "cv_pct": stats["cv_pct"],
                "prompt_tokens_p50": statistics.median(tokens),
                "ok": sum(record.status == "ok" for record in records),
                "blocked": sum(record.status == "blocked" for record in records),
                "error": sum(record.status == "error" for record in records),
            }
        )
    return reports


def _mode_report(
    walls_ns: list[int],
    samples: list[list[StepRecord]],
    order: list[AgentStep],
    peak_in_flight: int,
) -> ModeReport:
    stats = latency_distribution([wall / 1e6 for wall in walls_ns])
    return {
        "n": stats["n"],
        "p50_ms": stats["p50_ms"],
        "p95_ms": stats["p95_ms"],
        "p99_ms": stats["p99_ms"],
        "median_ms": stats["median_ms"],
        "mad_ms": stats["mad_ms"],
        "mean_ms": stats["mean_ms"],
        "stdev_ms": stats["stdev_ms"],
        "cv_pct": stats["cv_pct"],
        "tail_supported": stats["tail_supported"],
        "peak_in_flight": peak_in_flight,
        "samples_ms": [wall / 1e6 for wall in walls_ns],
        "steps": _step_reports(samples, order),
    }


def _with_callback_distribution(report: dict[str, object]) -> dict[str, object]:
    samples = report.pop("callback_samples_ms", [])
    if isinstance(samples, list) and len(samples) >= 2:
        durations = [float(value) for value in samples]
        report["callback_latency"] = latency_distribution(durations)
    return report


async def _allocation_probe(
    steps: list[AgentStep],
    manifests: Mapping[str, AgentManifest],
    agents_root: str,
    *,
    parallel_cap: int,
) -> dict[str, int | str]:
    """Trace one uncounted pass of each mode. Not included in the latency samples."""
    started_here = not tracemalloc.is_tracing()
    if started_here:
        tracemalloc.start()
    else:
        tracemalloc.clear_traces()
        tracemalloc.reset_peak()
    try:
        await _pass(
            steps,
            manifests,
            agents_root,
            parallel=False,
            parallel_cap=parallel_cap,
            instruments=None,
        )
        await _pass(
            steps,
            manifests,
            agents_root,
            parallel=True,
            parallel_cap=parallel_cap,
            instruments=None,
        )
        current, peak = tracemalloc.get_traced_memory()
    finally:
        if started_here:
            tracemalloc.stop()
    return {
        "current_bytes": current,
        "peak_bytes": peak,
        "scope": "one uncounted pass per mode after the timed samples",
    }


async def measure(
    *,
    warmup: int = CLI_WARMUP,
    samples: int = CLI_SAMPLES,
    parallel_cap: int = PARALLEL_CAP,
    agents_root: Path = AGENTS_ROOT,
) -> SuiteReport:
    """Warm up, then time interleaved solo and parallel passes of the catalog.

    Args:
        warmup: Discarded passes of each mode. Must be at least 0.
        samples: Counted pairs. Must be at least 2. Nearest-rank tails at n=30
            are one or two order statistics, so ``tail_supported`` stays false
            below 100.
        parallel_cap: Concurrent agent steps in the parallel mode.
        agents_root: Directory of ``Agents/{Name}/agent.yaml``.

    Returns:
        Distributions for both modes, per-step rows, and any non-ok steps.

    Raises:
        ValueError: When the sample, warmup, cap, or catalog arguments are unusable.
    """
    if warmup < 0 or samples < 2:
        raise ValueError("warmup must be non-negative and samples must be at least 2")
    if parallel_cap < 1:
        raise ValueError("parallel_cap must be at least 1")
    manifests = load_all_agent_manifests(agents_root)
    steps = catalog(manifests)
    if not steps:
        raise ValueError(f"no agent tasks under {agents_root}")
    root = str(agents_root)
    solo_walls: list[int] = []
    parallel_walls: list[int] = []
    solo_cpu: list[int] = []
    parallel_cpu: list[int] = []
    solo_samples: list[list[StepRecord]] = []
    parallel_samples: list[list[StepRecord]] = []
    failures: list[str] = []
    solo_peak = 1
    parallel_peak = 1
    instruments = SuiteInstruments()
    with _scripted_keys(manifests):
        for _ in range(warmup):
            solo_pass = await _pass(
                steps,
                manifests,
                root,
                parallel=False,
                parallel_cap=parallel_cap,
                instruments=instruments,
            )
            parallel_pass = await _pass(
                steps,
                manifests,
                root,
                parallel=True,
                parallel_cap=parallel_cap,
                instruments=instruments,
            )
            failures.extend(f"warmup {item}" for item in _failures(solo_pass.records))
            failures.extend(f"warmup {item}" for item in _failures(parallel_pass.records))
        instruments.reset()
        gc_before = gc_collections()
        usage_before = rusage_snapshot()
        for _ in range(samples):
            solo_pass = await _pass(
                steps,
                manifests,
                root,
                parallel=False,
                parallel_cap=parallel_cap,
                instruments=instruments,
            )
            parallel_pass = await _pass(
                steps,
                manifests,
                root,
                parallel=True,
                parallel_cap=parallel_cap,
                instruments=instruments,
            )
            solo_peak = max(solo_peak, solo_pass.peak_in_flight)
            parallel_peak = max(parallel_peak, parallel_pass.peak_in_flight)
            solo_walls.append(solo_pass.wall_ns)
            parallel_walls.append(parallel_pass.wall_ns)
            solo_cpu.append(solo_pass.cpu_ns)
            parallel_cpu.append(parallel_pass.cpu_ns)
            solo_samples.append(solo_pass.records)
            parallel_samples.append(parallel_pass.records)
            failures.extend(_failures(solo_pass.records))
            failures.extend(_failures(parallel_pass.records))
        gc_after = gc_collections()
        usage_after = rusage_snapshot()
        langchain = _with_callback_distribution(instruments.langchain_report())
        prometheus = instruments.prometheus_report()
        opentelemetry = instruments.otel_report()
        instruments.shutdown()
        traced = await _allocation_probe(steps, manifests, root, parallel_cap=parallel_cap)
    solo = _mode_report(solo_walls, solo_samples, steps, solo_peak)
    parallel = _mode_report(parallel_walls, parallel_samples, steps, parallel_peak)
    deltas = [
        right - left for left, right in zip(solo["samples_ms"], parallel["samples_ms"], strict=True)
    ]
    delta_median = statistics.median(deltas)
    delta_mad = statistics.median(abs(delta - delta_median) for delta in deltas)
    solo_p50 = solo["p50_ms"]
    return {
        "task": "agent_suite",
        "measured_at": datetime.now(UTC).isoformat(),
        "latency_kind": "scripted worker dispatch with LangChain callbacks, not provider latency",
        "command": "PYTHONPATH=Agents uv run python -m benchmark.run --task agent_suite",
        "protocol": {
            "clock": "time.perf_counter_ns",
            "warmup_passes": warmup,
            "samples": samples,
            "order": "each counted pair is solo then parallel; warmup pairs are discarded",
            "parallel_cap": parallel_cap,
            "parallel_cap_reason": "host agent limit is 3; the swarm.yaml I/O cap of 8 is not used",
            "percentile": "p50 is statistics.median; p95 and p99 are nearest-rank",
            "tail_supported_min_n": TAIL_MIN_N,
            "win_rule": "a win needs the paired delta to exceed 2x MAD and a second run",
            "catalog_source": "load_all_agent_manifests",
            "instruments": ["python", "langchain", "prometheus", "opentelemetry"],
        },
        "env": _environment(),
        "catalog": {
            "agents": len(manifests),
            "steps": len(steps),
            "tasks": [{"agent": step.agent, "task_id": step.task_id} for step in steps],
        },
        "modes": {"solo": solo, "parallel": parallel},
        "comparison": {
            "claim": "none",
            "runs": 1,
            "paired_delta_p50_ms": delta_median,
            "paired_delta_mad_ms": delta_mad,
            "delta_pct": (delta_median / solo_p50 * 100.0) if solo_p50 else None,
            "exceeds_two_dispersion": abs(delta_median) > (2.0 * delta_mad) if delta_mad else False,
        },
        "peak_rss_bytes": _peak_rss_bytes(),
        "rss_unit": "bytes",
        "instruments": {
            "python": {
                "cpu_ms": {
                    "solo": latency_distribution([value / 1e6 for value in solo_cpu]),
                    "parallel": latency_distribution([value / 1e6 for value in parallel_cpu]),
                },
                "rusage_delta": rusage_delta(usage_before, usage_after),
                "gc_collections_delta": [
                    after - before for before, after in zip(gc_before, gc_after, strict=True)
                ],
                "tracemalloc": traced,
            },
            "langchain": langchain,
            "prometheus": prometheus,
            "opentelemetry": opentelemetry,
        },
        "failures": failures,
    }


def write_report(report: SuiteReport, path: Path = RESULTS_PATH) -> Path:
    """Write the report JSON and return its path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return path


def format_report(report: SuiteReport) -> str:
    """Return a short text table of the two mode distributions."""
    catalog = report["catalog"]
    lines = [
        (
            f"agent_suite scripted dispatch  agents={catalog['agents']} "
            f"steps={catalog['steps']} samples={report['protocol']['samples']} "
            f"parallel_cap={report['protocol']['parallel_cap']}"
        ),
        f"{'mode':<10}{'n':>6}{'p50 ms':>12}{'p95 ms':>12}{'p99 ms':>12}{'MAD ms':>12}{'CV%':>8}",
    ]
    for name in ("solo", "parallel"):
        mode = report["modes"][name]
        lines.append(
            f"{name:<10}{mode['n']:>6}{mode['p50_ms']:>12.3f}{mode['p95_ms']:>12.3f}"
            f"{mode['p99_ms']:>12.3f}{mode['mad_ms']:>12.3f}{mode['cv_pct']:>8.2f}"
        )
    comparison = report["comparison"]
    delta_ms = comparison["paired_delta_p50_ms"]
    delta_pct = comparison["delta_pct"]
    pct = f"{delta_pct:.3f}%" if isinstance(delta_pct, float) else "n/a"
    ms = f"{delta_ms:.3f}" if isinstance(delta_ms, float) else "n/a"
    lines.append(f"paired delta p50 {ms} ms ({pct})  claim: {comparison['claim']}")
    lines.append(f"peak RSS {report['peak_rss_bytes']} {report['rss_unit']}")
    lines.extend(_format_instruments(report["instruments"]))
    if report["failures"]:
        lines.append(f"failures: {len(report['failures'])}")
        lines.extend(report["failures"][:20])
    return "\n".join(lines)


def _format_instruments(instruments: dict[str, object]) -> list[str]:
    lines: list[str] = []
    python = instruments.get("python")
    if isinstance(python, dict):
        cpu = python.get("cpu_ms")
        traced = python.get("tracemalloc")
        solo = cpu.get("solo") if isinstance(cpu, dict) else None
        parallel = cpu.get("parallel") if isinstance(cpu, dict) else None
        solo_p50 = solo.get("p50_ms") if isinstance(solo, dict) else None
        parallel_p50 = parallel.get("p50_ms") if isinstance(parallel, dict) else None
        peak = traced.get("peak_bytes") if isinstance(traced, dict) else None
        lines.append(
            f"python cpu p50 solo {solo_p50} ms parallel {parallel_p50} ms"
            f"  tracemalloc peak {peak} bytes"
        )
    langchain = instruments.get("langchain")
    if isinstance(langchain, dict):
        lines.append(
            "langchain "
            f"llm_ends={langchain.get('llm_ends')} "
            f"errors={langchain.get('llm_errors')} "
            f"tokens={langchain.get('total_tokens')}"
        )
    prometheus = instruments.get("prometheus")
    if isinstance(prometheus, dict):
        lines.append(f"prometheus steps_total={prometheus.get('steps_total')}")
    otel = instruments.get("opentelemetry")
    if isinstance(otel, dict):
        lines.append(
            f"opentelemetry spans={otel.get('span_count')} errors={otel.get('error_spans')}"
        )
    return lines


def main(argv: list[str] | None = None) -> int:
    """Run the protocol and write ``results/agent_suite/latest.json``.

    Returns:
        0 when every counted step is ok, 1 when any step is blocked or errors.
    """
    parser = argparse.ArgumentParser(description="Scripted solo and parallel agent-task bench")
    parser.add_argument("--samples", type=int, default=CLI_SAMPLES)
    parser.add_argument("--warmup", type=int, default=CLI_WARMUP)
    parser.add_argument("--parallel-cap", type=int, default=PARALLEL_CAP)
    args = parser.parse_args(argv)
    report = asyncio.run(
        measure(warmup=args.warmup, samples=args.samples, parallel_cap=args.parallel_cap)
    )
    path = write_report(report)
    print(format_report(report))
    print(f"wrote {path}")
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
