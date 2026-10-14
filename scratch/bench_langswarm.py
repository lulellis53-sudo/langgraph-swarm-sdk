#!/usr/bin/env python3
"""Benchmark and profile LangSwarm in Core/Sdk.

Measures:
1. Swarm compilation time with 2 and 4 agents.
2. Handoff tool resolution & dispatch latency (micro-bench and end-to-end swarm dispatch).
3. Message state accumulation and token consumption tracking across 50 successive turns.
4. Memory stability and peak RSS under 50 sequential invocations.

Computes quantitative metrics: P50, P95, Mean, Min, Max, and Peak RSS.
"""

from __future__ import annotations

import gc
import math
import resource
import sys
import time
import tracemalloc
from collections.abc import Sequence
from typing import Any, List, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

import sdk
from sdk import Swarm, SwarmAgent, create_handoff


# --- Helpers & Statistics ---

def percentile(data: list[float], pct: float) -> float:
    """Calculate percentile using nearest rank method."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (pct / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_data[int(k)]
    d0 = sorted_data[int(f)] * (c - k)
    d1 = sorted_data[int(c)] * (k - f)
    return d0 + d1


def compute_stats(data: list[float]) -> dict[str, float]:
    """Calculate mean, std, p50, p95, min, max for a sequence of numbers."""
    if not data:
        return {"mean": 0.0, "p50": 0.0, "p95": 0.0, "min": 0.0, "max": 0.0}
    mean = sum(data) / len(data)
    variance = sum((x - mean) ** 2 for x in data) / len(data)
    std = math.sqrt(variance)
    return {
        "mean": mean,
        "std": std,
        "p50": percentile(data, 50.0),
        "p95": percentile(data, 95.0),
        "min": min(data),
        "max": max(data),
    }


def get_peak_rss_mb() -> float:
    """Return peak RSS in Megabytes (Darwin ru_maxrss is in bytes)."""
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return usage / (1024.0 * 1024.0)
    return usage / 1024.0  # Linux is KB


# --- Mock Models for Zero-Network Benchmarking ---

class BenchmarkChatModel(BaseChatModel):
    """Deterministic chat model for benchmarking without network overhead."""

    agent_name: str
    target_handoff: Optional[str] = None
    prompt_tokens_per_msg: int = 25
    completion_tokens_fixed: int = 20

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        input_tokens = sum(
            len(m.content) // 4 + self.prompt_tokens_per_msg
            for m in messages
            if isinstance(m.content, str)
        )
        output_tokens = self.completion_tokens_fixed

        if self.target_handoff:
            tool_call = {
                "name": f"transfer_to_{self.target_handoff}",
                "args": {},
                "id": f"call_handoff_{len(messages)}",
                "type": "tool_call",
            }
            msg = AIMessage(
                content="",
                tool_calls=[tool_call],
                usage_metadata={
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": input_tokens + output_tokens,
                },
            )
        else:
            msg = AIMessage(
                content=f"Agent {self.agent_name} processed {len(messages)} messages.",
                usage_metadata={
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": input_tokens + output_tokens,
                },
            )
        return ChatResult(generations=[ChatGeneration(message=msg)])

    @property
    def _llm_type(self) -> str:
        return "bench-mock-llm"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> Any:
        return self


# --- Benchmark Functions ---

def benchmark_compilation(agent_counts: tuple[int, ...] = (2, 4), iterations: int = 50) -> dict[int, dict[str, float]]:
    """Benchmark Swarm compilation latency for given agent counts."""
    print(f"\n--- [1] Swarm Compilation Latency ({iterations} iterations each) ---")
    results = {}

    for count in agent_counts:
        durations_ms: list[float] = []
        for _ in range(iterations):
            agents = [
                SwarmAgent(
                    name=f"Agent_{i}",
                    system_prompt=f"System prompt for specialist agent {i}",
                    model=BenchmarkChatModel(agent_name=f"Agent_{i}"),
                    enable_middleware=False,
                )
                for i in range(count)
            ]
            swarm = Swarm(
                agents=agents,
                default_active_agent="Agent_0",
                checkpointer=InMemorySaver(),
            )
            gc.collect()
            t0 = time.perf_counter()
            app = swarm.compile()
            t1 = time.perf_counter()
            durations_ms.append((t1 - t0) * 1000.0)

        stats = compute_stats(durations_ms)
        results[count] = stats
        print(f"Agents={count:2d} | Mean={stats['mean']:.3f} ms | P50={stats['p50']:.3f} ms | P95={stats['p95']:.3f} ms | Min={stats['min']:.3f} ms | Max={stats['max']:.3f} ms")

    return results


def benchmark_handoff_latency(tool_iterations: int = 500, e2e_iterations: int = 50) -> dict[str, dict[str, float]]:
    """Benchmark handoff tool dispatch latency: micro-invocation and end-to-end swarm turn."""
    print(f"\n--- [2] Handoff Tool Resolution & Dispatch Latency ---")

    # 1. Micro-benchmark: direct tool invocation dispatch
    handoff_tool = create_handoff("WorkerAgent")
    call_payload = {
        "name": "transfer_to_WorkerAgent",
        "args": {"state": {"messages": [HumanMessage(content="handoff request")]}},
        "id": "call_123",
        "type": "tool_call",
    }
    
    # Warmup
    for _ in range(10):
        _ = handoff_tool.invoke(call_payload)

    tool_latencies_us: list[float] = []
    for _ in range(tool_iterations):
        t0 = time.perf_counter()
        res = handoff_tool.invoke(call_payload)
        t1 = time.perf_counter()
        tool_latencies_us.append((t1 - t0) * 1_000_000.0)

    tool_stats = compute_stats(tool_latencies_us)
    print(f"Direct Tool Invoke ({tool_iterations} runs): Mean={tool_stats['mean']:.2f} µs | P50={tool_stats['p50']:.2f} µs | P95={tool_stats['p95']:.2f} µs | Min={tool_stats['min']:.2f} µs | Max={tool_stats['max']:.2f} µs")

    # 2. End-to-end swarm handoff turn dispatch latency (Dispatcher -> Handoff Tool -> WorkerAgent)
    e2e_latencies_ms: list[float] = []
    for i in range(e2e_iterations):
        dispatcher = SwarmAgent(
            name="Dispatcher",
            system_prompt="Route requests",
            model=BenchmarkChatModel(agent_name="Dispatcher", target_handoff="Worker"),
            enable_middleware=False,
        )
        worker = SwarmAgent(
            name="Worker",
            system_prompt="Execute task",
            model=BenchmarkChatModel(agent_name="Worker", target_handoff=None),
            enable_middleware=False,
        )
        swarm = Swarm([dispatcher, worker], default_active_agent="Dispatcher", checkpointer=InMemorySaver())
        swarm.compile()

        t0 = time.perf_counter()
        out = swarm.run("Please route this task", thread_id=f"thread_e2e_{i}")
        t1 = time.perf_counter()
        assert out.get("active_agent") == "Worker", f"Expected Worker, got {out.get('active_agent')}"
        e2e_latencies_ms.append((t1 - t0) * 1000.0)

    e2e_stats = compute_stats(e2e_latencies_ms)
    print(f"Swarm Handoff E2E Turn ({e2e_iterations} runs): Mean={e2e_stats['mean']:.3f} ms | P50={e2e_stats['p50']:.3f} ms | P95={e2e_stats['p95']:.3f} ms | Min={e2e_stats['min']:.3f} ms | Max={e2e_stats['max']:.3f} ms")

    return {"tool_invoke_us": tool_stats, "e2e_handoff_ms": e2e_stats}


def benchmark_sequential_turns(turns: int = 50) -> dict[str, Any]:
    """Benchmark message state accumulation, token consumption, and memory footprint across 50 successive turns."""
    print(f"\n--- [3 & 4] Sequential Multi-Turn Invocation, Token Consumption & Memory Footprint ({turns} turns) ---")

    agent_a = SwarmAgent(
        name="Alice",
        system_prompt="You are Alice, coordinator agent.",
        model=BenchmarkChatModel(agent_name="Alice", target_handoff=None),
        enable_middleware=False,
    )
    agent_b = SwarmAgent(
        name="Bob",
        system_prompt="You are Bob, helper agent.",
        model=BenchmarkChatModel(agent_name="Bob", target_handoff=None),
        enable_middleware=False,
    )

    checkpointer = InMemorySaver()
    swarm = Swarm([agent_a, agent_b], default_active_agent="Alice", checkpointer=checkpointer)
    swarm.compile()

    tracemalloc.start()
    gc.collect()

    initial_peak_rss = get_peak_rss_mb()
    mem_start, _ = tracemalloc.get_traced_memory()

    turn_latencies_ms: list[float] = []
    state_accumulation: list[dict[str, Any]] = []
    thread_id = "bench_session_50_turns"

    cumulative_input_tokens = 0
    cumulative_output_tokens = 0

    checkpoint_steps = [1, 10, 20, 30, 40, 50]

    for turn in range(1, turns + 1):
        prompt = f"Turn {turn}: benchmark sequential query payload with state tracking."
        
        t0 = time.perf_counter()
        state = swarm.run(prompt, thread_id=thread_id)
        t1 = time.perf_counter()
        
        latency = (t1 - t0) * 1000.0
        turn_latencies_ms.append(latency)

        messages = state.get("messages", [])
        msg_count = len(messages)

        # Collect tokens from latest AI response
        last_msg = messages[-1] if messages else None
        usage = getattr(last_msg, "usage_metadata", None) or {}
        cumulative_input_tokens += usage.get("input_tokens", 0)
        cumulative_output_tokens += usage.get("output_tokens", 0)

        current_heap, peak_heap = tracemalloc.get_traced_memory()
        current_peak_rss = get_peak_rss_mb()

        entry = {
            "turn": turn,
            "latency_ms": latency,
            "messages_count": msg_count,
            "cumulative_input_tokens": cumulative_input_tokens,
            "cumulative_output_tokens": cumulative_output_tokens,
            "cumulative_total_tokens": cumulative_input_tokens + cumulative_output_tokens,
            "heap_current_kb": current_heap / 1024.0,
            "heap_peak_kb": peak_heap / 1024.0,
            "peak_rss_mb": current_peak_rss,
        }
        state_accumulation.append(entry)

        if turn in checkpoint_steps:
            print(
                f"Turn {turn:2d} | Latency={latency:.3f} ms | Messages={msg_count:3d} | "
                f"Total Tokens={entry['cumulative_total_tokens']:5d} | "
                f"Heap={entry['heap_current_kb']:.1f} KB (Peak={entry['heap_peak_kb']:.1f} KB) | "
                f"Peak RSS={current_peak_rss:.2f} MB"
            )

    latency_stats = compute_stats(turn_latencies_ms)
    final_heap, peak_heap = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    final_peak_rss = get_peak_rss_mb()

    print(f"\nSequential Turn Latency Stats ({turns} turns):")
    print(f"  Mean: {latency_stats['mean']:.3f} ms")
    print(f"  P50 : {latency_stats['p50']:.3f} ms")
    print(f"  P95 : {latency_stats['p95']:.3f} ms")
    print(f"  Min : {latency_stats['min']:.3f} ms")
    print(f"  Max : {latency_stats['max']:.3f} ms")
    print(f"\nMemory Profile:")
    print(f"  Initial Peak RSS : {initial_peak_rss:.2f} MB")
    print(f"  Final Peak RSS   : {final_peak_rss:.2f} MB (Delta: {final_peak_rss - initial_peak_rss:+.2f} MB)")
    print(f"  Final Heap Alloc : {final_heap / 1024.0:.2f} KB")
    print(f"  Peak Traced Heap : {peak_heap / 1024.0:.2f} KB")
    print(f"  Accumulated State: {state_accumulation[-1]['messages_count']} messages, {state_accumulation[-1]['cumulative_total_tokens']} tokens")

    return {
        "latency_stats": latency_stats,
        "initial_peak_rss_mb": initial_peak_rss,
        "final_peak_rss_mb": final_peak_rss,
        "peak_rss_mb": final_peak_rss,
        "final_heap_kb": final_heap / 1024.0,
        "peak_heap_kb": peak_heap / 1024.0,
        "final_messages": state_accumulation[-1]["messages_count"],
        "final_tokens": state_accumulation[-1]["cumulative_total_tokens"],
        "checkpoints": [state_accumulation[t - 1] for t in checkpoint_steps],
    }


def main() -> None:
    print("=" * 80)
    print("  LangSwarm (Core/Sdk) Comprehensive Profiling & Performance Benchmark")
    print("=" * 80)

    # 1. Compilation
    compilation_results = benchmark_compilation(agent_counts=(2, 4), iterations=50)

    # 2. Handoff tool dispatch
    handoff_results = benchmark_handoff_latency(tool_iterations=500, e2e_iterations=50)

    # 3 & 4. 50 Sequential turns, state accumulation, token consumption, memory stability
    sequential_results = benchmark_sequential_turns(turns=50)

    print("\n" + "=" * 80)
    print("                      BENCHMARK SUMMARY REPORT")
    print("=" * 80)
    print(f"1. Swarm Compilation Latency:")
    print(f"   - 2 Agents: Mean={compilation_results[2]['mean']:.3f} ms | P50={compilation_results[2]['p50']:.3f} ms | P95={compilation_results[2]['p95']:.3f} ms")
    print(f"   - 4 Agents: Mean={compilation_results[4]['mean']:.3f} ms | P50={compilation_results[4]['p50']:.3f} ms | P95={compilation_results[4]['p95']:.3f} ms")
    print(f"2. Handoff Tool Resolution & Dispatch:")
    print(f"   - Direct Tool Invoke : Mean={handoff_results['tool_invoke_us']['mean']:.2f} µs | P50={handoff_results['tool_invoke_us']['p50']:.2f} µs | P95={handoff_results['tool_invoke_us']['p95']:.2f} µs")
    print(f"   - Swarm E2E Handoff  : Mean={handoff_results['e2e_handoff_ms']['mean']:.3f} ms | P50={handoff_results['e2e_handoff_ms']['p50']:.3f} ms | P95={handoff_results['e2e_handoff_ms']['p95']:.3f} ms")
    print(f"3. 50 Sequential Turns Execution:")
    print(f"   - Turn Latency       : Mean={sequential_results['latency_stats']['mean']:.3f} ms | P50={sequential_results['latency_stats']['p50']:.3f} ms | P95={sequential_results['latency_stats']['p95']:.3f} ms")
    print(f"   - State Accumulation : Initial=2 msgs -> Final={sequential_results['final_messages']} msgs")
    print(f"   - Token Consumption  : {sequential_results['final_tokens']} total tokens accumulated")
    print(f"4. Memory Stability & Footprint:")
    print(f"   - Peak RSS           : {sequential_results['peak_rss_mb']:.2f} MB")
    print(f"   - Peak Traced Heap   : {sequential_results['peak_heap_kb']:.2f} KB")
    print(f"   - Memory Delta (RSS) : {sequential_results['final_peak_rss_mb'] - sequential_results['initial_peak_rss_mb']:+.2f} MB")
    print("=" * 80)


if __name__ == "__main__":
    main()
