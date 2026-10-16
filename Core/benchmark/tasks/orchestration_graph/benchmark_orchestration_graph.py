"""Timed orchestration graph invoke (offline, no API keys)."""

from __future__ import annotations

import statistics
import time

from langchain_core.language_models.fake_chat_models import FakeListChatModel

from Core.benchmark.protocol import BenchmarkResult
from orchestration.graph import build_graph

_ITERATIONS = 20
_WARMUP = 3


def _single_invoke_ms() -> float:
    llm = FakeListChatModel(responses=["plan steps", "final"])
    graph = build_graph(llm, lambda plan: "research notes")
    start = time.perf_counter()
    out = graph.invoke({"goal": "benchmark goal"})
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    for key in ("goal", "plan", "research", "answer"):
        if key not in out:
            raise RuntimeError(f"missing state key {key}: {out!r}")
    if not out["plan"] or not out["research"] or not out["answer"]:
        raise RuntimeError(f"empty stage output: {out!r}")
    if out.get("answer") != "final":
        raise RuntimeError(f"unexpected answer: {out!r}")
    return elapsed_ms


def run_benchmark() -> BenchmarkResult:
    for _ in range(_WARMUP):
        _single_invoke_ms()
    samples = [_single_invoke_ms() for _ in range(_ITERATIONS)]
    p50 = statistics.median(samples)
    passed = p50 < 5000.0
    return BenchmarkResult(name="orchestration_graph", p50_ms=p50, passed=passed)
