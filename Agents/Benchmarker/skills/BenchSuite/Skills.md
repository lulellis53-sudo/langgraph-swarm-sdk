---
name: CreateBenchmarkSuite
description: Automated skill to design, synthesize, and execute statistical benchmark suites for LangGraph Swarm, agent workflows, and memory subsystems.
---

# CreateBenchmarkSuite: Performance Benchmarking & Profiling Skill

## Overview

The `CreateBenchmarkSuite` skill equips the **Benchmarker** agent with automated protocols to profile, measure, and analyze high-performance multi-agent swarms, token throughput, and memory stability across execution turns.

---

## Benchmarking Protocol & Architecture

```text
       ┌────────────────────────────────────────────────────────┐
       │             BENCHMARK SUITE PIPELINE                   │
       ├────────────────────────────────────────────────────────┤
       │  [Phase 1] Harness Setup (Warmup runs & baseline calibration)
       │  [Phase 2] Latency Sampling (P50, P90, P95, P99, Mean) │
       │  [Phase 3] Throughput & Concurrency Stress Test        │
       │  [Phase 4] Memory Profiling (Peak RSS, Tracemalloc)    │
       │  [Phase 5] Quantitative Statistical Report & Δ% Matrix │
       └────────────────────────────────────────────────────────┘
```

---

## 1. Key Metrics & Targets

| Metric | Target / SLA | Formula / Methodology |
| :--- | :--- | :--- |
| **Swarm Graph Compilation** | < 15 ms | `time.perf_counter()` over 100 warm compilations |
| **Handoff Tool Resolution** | < 2 ms | Time to inspect and invoke `create_handoff_tool` |
| **P50 Latency** | Baseline P50 | Median execution time across 50 iterations |
| **P95 / P99 Latency** | < 2.5x P50 | High-tail distribution percentile |
| **Memory Drift (Leak Check)** | 0% unbounded growth | Delta RSS after 100 turns through `tracemalloc` |
| **Token Budget Compliance** | ≤ Configured ceiling | Pruned via `build_default_middleware` |

---

## 2. Standard Benchmark Harness Recipe

When synthesizing benchmark scripts (saved in `scratch/bench_<target>.py`):

```python
"""Automated LangGraph Swarm Performance Benchmark."""

import gc
import statistics
import time
import tracemalloc
from typing import Any

from Core.Sdk import Swarm, SwarmAgent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver


def run_benchmark(iterations: int = 50) -> dict[str, Any]:
    # 1. Setup Mock Specialist Agents
    fake_model = FakeMessagesListChatModel(
        responses=[AIMessage(content="Benchmark test response")]
    )
    agents = [
        SwarmAgent(name=f"Agent_{i}", system_prompt=f"Specialist {i}", model=fake_model)
        for i in range(4)
    ]
    swarm = Swarm(agents=agents, default_active_agent="Agent_0", checkpointer=InMemorySaver())

    # 2. Warmup
    for _ in range(5):
        swarm.compile()

    # 3. Compilation Latency Profiling
    compilation_times: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        swarm.compile()
        compilation_times.append((time.perf_counter() - t0) * 1000.0)

    # 4. Turn Execution & Memory Profiling
    tracemalloc.start()
    execution_times: list[float] = []
    for i in range(iterations):
        t0 = time.perf_counter()
        swarm.run(f"Benchmark iteration {i}", thread_id=f"thread_{i % 5}")
        execution_times.append((time.perf_counter() - t0) * 1000.0)

    current_mem, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    compilation_times.sort()
    execution_times.sort()

    return {
        "compilation_p50_ms": statistics.median(compilation_times),
        "compilation_p95_ms": compilation_times[int(0.95 * len(compilation_times))],
        "execution_p50_ms": statistics.median(execution_times),
        "execution_p95_ms": execution_times[int(0.95 * len(execution_times))],
        "peak_rss_kb": peak_mem / 1024.0,
    }
```

---

## 3. Execution Commands & Reporting

1. Run benchmark via `uv`:
   ```bash
   uv run python scratch/bench_<target>.py
   ```
2. Report results using GitHub Markdown tables including:
   - Median (P50), P95, and P99 latency.
   - Standard deviation ($\sigma$).
   - Peak RSS and memory drift.
   - Comparative $\Delta\%$ improvement versus prior baseline.
