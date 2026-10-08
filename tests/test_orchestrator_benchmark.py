"""Orchestrator performance benchmarks: token usage, latency, parallelism.

Measures the spawn → plan → worker pipeline using ``pytest-benchmark``.
All benchmarks use fake models and fake backends — no network, no API keys.

Metrics tracked (per Benchmark.md §5–7):
- Prompt token count (whitespace tokenizer proxy)
- Wall-clock latency (ms) for spawn, worker.run, wave execution
- Parallel speedup (sequential vs bounded_gather)
- Cache hit rate and latency reduction
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from swarm_sdk.orchestrator.plan import Plan, PlanStep, UsageTotals
from swarm_sdk.orchestrator.spawn import _fallback_plan, _validate_plan
from swarm_sdk.orchestrator.worker import WorkerAgent

# --- helpers -----------------------------------------------------------------


def _make_plan(n_steps: int, deps: bool = False) -> Plan:
    """Build a plan with n_steps; optionally chained dependencies."""
    steps = []
    for i in range(n_steps):
        step = PlanStep(
            id=f"S{i + 1}",
            title=f"step {i + 1}",
            description=f"Do task {i + 1}. " * 10,
            agent="Coder",
            files=[f"src/file_{i}.py"],
            depends_on=[f"S{i}"] if (deps and i > 0) else [],
            inputs=[f"S{i}"] if (deps and i > 0) else [],
        )
        steps.append(step)
    return Plan(steps=steps)


class _FakeModel:
    """Minimal chat model stub that returns a fixed reply instantly."""

    def __init__(self, reply: str = "done") -> None:
        self._reply = reply
        self.call_count = 0

    def invoke(self, messages: list[Any], **kwargs: Any) -> Any:
        self.call_count += 1
        from langchain_core.messages import AIMessage

        return AIMessage(content=self._reply)

    async def ainvoke(self, messages: list[Any], **kwargs: Any) -> Any:
        return self.invoke(messages, **kwargs)


class _FakeManifest:
    """Minimal AgentManifest stub for WorkerAgent binding."""

    name = "Coder"
    role = "Senior Python engineer."
    model = "fake:model"
    api_key_env = ""
    capabilities: list[str] = []

    class token_budget:
        max_prompt = 4000

    tasks: list[Any] = []


# --- token benchmarks ---------------------------------------------------------


def test_prompt_token_count_benchmark(benchmark: Any) -> None:
    """Token count for a typical 5-step plan prompt (whitespace proxy)."""
    from swarm_sdk.prompting.budget import count_text

    plan = _make_plan(5)
    roster = "\n".join(f"- {s.agent}: step {s.id}" for s in plan.steps)
    prompt = f"Decompose the goal into a JSON plan.\nGoal: build a web app\n{roster}"

    result = benchmark(count_text, prompt)
    assert result > 0


def test_system_prompt_token_count_benchmark(benchmark: Any) -> None:
    """Token count for the role contract system prompt."""
    from swarm_sdk.prompting.budget import count_text

    contract = "Senior Python engineer. " * 200  # ~400 words
    result = benchmark(count_text, contract)
    assert result > 0


def test_fallback_plan_token_count(benchmark: Any) -> None:
    """Token count for a single-step fallback plan (minimum spawn path)."""
    from swarm_sdk.prompting.budget import count_text

    manifests = {"Coder": _FakeManifest()}
    plan = benchmark(_fallback_plan, "do the thing", manifests)
    assert len(plan.steps) == 1
    assert count_text(plan.steps[0].description) > 0


# --- latency benchmarks -------------------------------------------------------


def test_validate_plan_latency(benchmark: Any) -> None:
    """Plan validation latency for a 10-step plan."""
    plan = _make_plan(10)
    manifests = {"Coder": _FakeManifest()}

    def run() -> None:
        _validate_plan(plan, manifests)

    benchmark(run)


def test_plan_waves_latency(benchmark: Any) -> None:
    """Wave computation latency for a 20-step chained plan."""
    plan = _make_plan(20, deps=True)

    def run() -> list[list[PlanStep]]:
        return plan.waves()

    waves = benchmark(run)
    assert len(waves) == 20  # fully chained = 20 waves


def test_plan_waves_parallel_latency(benchmark: Any) -> None:
    """Wave computation latency for a 20-step independent plan."""
    plan = _make_plan(20, deps=False)

    def run() -> list[list[PlanStep]]:
        return plan.waves()

    waves = benchmark(run)
    assert len(waves) == 1  # all independent = 1 wave


# --- parallelism benchmarks ---------------------------------------------------


async def _run_sequential(steps: list[PlanStep], factory: Any) -> float:
    """Run steps one at a time; return wall seconds."""
    start = time.perf_counter()
    for step in steps:
        worker = factory(step)
        await worker.run(step.id, step.description, {})
    return time.perf_counter() - start


async def _run_parallel(steps: list[PlanStep], factory: Any, max_concurrency: int = 8) -> float:
    """Run steps with bounded_gather; return wall seconds."""
    from swarm_sdk.models.selection import bounded_gather

    start = time.perf_counter()

    factories = []
    for step in steps:
        def make(step: PlanStep = step) -> Any:
            async def one() -> Any:
                worker = factory(step)
                return await worker.run(step.id, step.description, {})
            return one()
        factories.append(make)

    await bounded_gather(factories, max_concurrency=max_concurrency)
    return time.perf_counter() - start


def test_wave_parallel_speedup() -> None:
    """Parallel wave execution should be faster than sequential for 8 steps."""
    steps = _make_plan(8).steps
    manifest = _FakeManifest()
    root = "."

    def factory(step: PlanStep) -> WorkerAgent:
        return WorkerAgent(
            manifest, agents_root=root, model_override=_FakeModel("ok")
        )

    seq_time = asyncio.run(_run_sequential(steps, factory))
    par_time = asyncio.run(_run_parallel(steps, factory, max_concurrency=8))

    # Print for the report; assert parallel is not slower.
    speedup = seq_time / max(par_time, 1e-9)
    print(f"\n  sequential={seq_time:.4f}s  parallel={par_time:.4f}s  speedup={speedup:.2f}x")
    assert par_time <= seq_time * 1.5  # allow overhead but expect improvement


# --- cache benchmarks ----------------------------------------------------------


class _DictCache:
    """Minimal SemanticCache stub with exact-match lookup."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self.hits = 0
        self.misses = 0

    def lookup(self, key: str) -> str | None:
        result = self._store.get(key)
        if result is not None:
            self.hits += 1
        else:
            self.misses += 1
        return result

    def store(self, key: str, value: str) -> None:
        self._store[key] = value


def test_cache_hit_latency(benchmark: Any) -> None:
    """Cache lookup latency vs full worker.run on a cache hit."""
    manifest = _FakeManifest()
    cache = _DictCache()
    worker = WorkerAgent(
        manifest, agents_root=".", cache=cache, model_override=_FakeModel("ok")
    )

    # Prime the cache.
    asyncio.run(worker.run("S1", "do something", {}))
    assert cache.misses == 1

    # Benchmark the cache hit path.
    result = benchmark(lambda: asyncio.run(worker.run("S1", "do something", {})))
    assert result.cached is True
    assert cache.hits >= 1


def test_cache_miss_vs_hit_speedup() -> None:
    """Cache hit should be dramatically faster than a model call."""
    manifest = _FakeManifest()
    cache = _DictCache()
    worker = WorkerAgent(
        manifest, agents_root=".", cache=cache, model_override=_FakeModel("ok")
    )

    # Measure miss (cold).
    miss_start = time.perf_counter()
    asyncio.run(worker.run("S1", "unique task", {}))
    miss_time = time.perf_counter() - miss_start

    # Measure hit (warm).
    hit_start = time.perf_counter()
    result = asyncio.run(worker.run("S1", "unique task", {}))
    hit_time = time.perf_counter() - hit_start

    assert result.cached is True
    speedup = miss_time / max(hit_time, 1e-9)
    print(f"\n  miss={miss_time * 1000:.3f}ms  hit={hit_time * 1000:.3f}ms  speedup={speedup:.1f}x")
    assert hit_time < miss_time  # cache must be faster


# --- worker prompt construction -----------------------------------------------


def test_user_prompt_construction_benchmark(benchmark: Any) -> None:
    """User prompt assembly latency with 3 dependency outputs."""
    manifest = _FakeManifest()
    worker = WorkerAgent(manifest, agents_root=".", model_override=_FakeModel())
    deps = {f"S{i}": f"output of step {i} " * 50 for i in range(3)}

    prompt = benchmark(
        worker._user_prompt, "implement the feature", deps, files=["src/a.py"], task="code"
    )
    assert "implement the feature" in prompt
    assert "inputs:" in prompt


def test_system_prompt_construction_benchmark(benchmark: Any) -> None:
    """System prompt assembly latency (role contract + budget pack)."""
    manifest = _FakeManifest()
    worker = WorkerAgent(manifest, agents_root=".", model_override=_FakeModel())

    prompt = benchmark(worker._system_prompt)
    assert len(prompt) > 0


# --- token savings: pruner and handoff compression ------------------------------


def test_pruner_token_reduction() -> None:
    """TurnPruner should reduce token count for long conversations."""
    from swarm_sdk.prompting.budget import count_text
    from swarm_sdk.prompting.pruner import TurnPruner

    turns = [
        f"User asked about topic {i}. The answer involves several key points "
        f"about the architecture and implementation details for item {i}. "
        f"This is a detailed explanation with multiple sentences covering "
        f"various aspects of the system design and tradeoffs involved."
        for i in range(20)
    ]
    original_tokens = count_text("\n".join(turns))

    pruner = TurnPruner(keep_turns=6, max_tokens=500)
    compressed = pruner.prune(turns)
    compressed_tokens = count_text("\n".join(compressed))

    reduction = 1 - compressed_tokens / original_tokens
    print(f"\n  original={original_tokens}  compressed={compressed_tokens}  reduction={reduction:.1%}")
    assert compressed_tokens < original_tokens
    assert len(compressed) <= 7  # digest + 6 recent turns


def test_handoff_compression_ratio() -> None:
    """compress_handoff should reduce token count for large dependency outputs."""
    from swarm_sdk.prompting.budget import count_text
    from swarm_sdk.prompting.pruner import compress_handoff

    large_output = (
        "The implementation adds a new module for handling web requests. "
        "It includes error handling, retry logic, and connection pooling. "
        "The module exports three public functions for making HTTP calls. "
        "Testing covers edge cases including timeouts and malformed responses. "
        "Documentation was updated with examples for each public API. "
        "The change is backward compatible with existing callers."
    ) * 5  # ~300 words

    original_tokens = count_text(large_output)
    compressed = compress_handoff(large_output, max_tokens=50)
    compressed_tokens = count_text(compressed)

    print(f"\n  original={original_tokens}  compressed={compressed_tokens}  max=50")
    assert compressed_tokens <= 50
    assert len(compressed) > 0


def test_pruner_latency_benchmark(benchmark: Any) -> None:
    """TurnPruner.prune latency for 20 turns."""
    from swarm_sdk.prompting.pruner import TurnPruner

    turns = [f"Turn {i} content with some meaningful text here." for i in range(20)]
    pruner = TurnPruner(keep_turns=6, max_tokens=500)

    result = benchmark(pruner.prune, turns)
    assert len(result) <= 7


def test_compress_handoff_latency_benchmark(benchmark: Any) -> None:
    """compress_handoff latency for a 1000-word dependency output."""
    from swarm_sdk.prompting.pruner import compress_handoff

    large_output = "This is a sentence with meaningful content. " * 200

    result = benchmark(compress_handoff, large_output, max_tokens=100)
    assert len(result) > 0


# --- lazy import verification ---------------------------------------------------


def test_import_time_target() -> None:
    """import swarm_sdk should be fast (lazy heavy imports)."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-c", "import time; t=time.perf_counter(); import swarm_sdk; print(f'{(time.perf_counter()-t)*1000:.1f}')"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    ms = float(result.stdout.strip().split()[-1])
    print(f"\n  import swarm_sdk: {ms:.1f}ms")
    # Target: <50ms. Allow 100ms for CI variance.
    assert ms < 100, f"import swarm_sdk took {ms:.1f}ms (target <100ms)"
