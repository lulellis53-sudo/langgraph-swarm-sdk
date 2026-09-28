"""Python leg: LangGraph plan engine vs the wave scheduler, scripted chat.

Runs the 20-task ``swarm.bench.tasks`` suite through both plan-execution
engines with a deterministic scripted ``chat_auto`` (no live LLM, no
network) and reports wall time, steps OK, and peak RSS (VmHWM before/after)
per engine. Import of the LangGraph engine is guarded: when the engine has
not landed, the leg skips with a reason instead of failing the matrix.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import contextmanager
from typing import Any

from benchmatrix.harness import STATUS_OK, STATUS_SKIP, Leg, LegResult

WHY = (
    "leader em buscas 27.100/mês, checkpointing nativo, time-travel debugging, "
    "controle determinístico de rotas"
)
NOT_LANDED = "langgraph engine not landed yet"

# One chat call per step, deterministic content, no tool calls: the worker
# loop terminates each step on the first scripted response.
SCRIPTED_CONTENT = "RESPOSTA: scripted-ok"


def python_langgraph_leg() -> Leg:
    return Leg(
        leg_id="python-langgraph",
        language="Python",
        sdk="LangGraph",
        why=WHY,
        runner=run_python_leg,
    )


def run_python_leg() -> LegResult:
    try:
        from swarm.orchestrator.graph import run_plan_langgraph
    except ImportError:
        return _skip(NOT_LANDED)

    from swarm.agents import WorkerAgent
    from swarm.agents.base import Plan
    from swarm.bench.tasks import TASKS

    tasks = list(TASKS)
    rss_before = _peak_rss_mb()

    wave = _run_wave(tasks)
    langgraph = _run_langgraph(tasks, run_plan_langgraph, WorkerAgent, Plan)
    rss_after = _peak_rss_mb()

    return LegResult(
        leg_id="python-langgraph",
        language="Python",
        sdk="LangGraph",
        why=WHY,
        status=STATUS_OK,
        metrics={
            "tasks": len(tasks),
            "wave": wave,
            "langgraph": langgraph,
            "rss_before_mb": rss_before,
            "rss_after_mb": rss_after,
            "rss_delta_mb": rss_after - rss_before,
        },
    )


def _skip(reason: str) -> LegResult:
    return LegResult(
        leg_id="python-langgraph",
        language="Python",
        sdk="LangGraph",
        why=WHY,
        status=STATUS_SKIP,
        skip_reason=reason,
    )


def _peak_rss_mb() -> float:
    """Peak RSS in MB from /proc/self/status VmHWM; 0.0 when unavailable."""
    try:
        with open("/proc/self/status", encoding="ascii") as fh:
            for line in fh:
                if line.startswith("VmHWM:"):
                    return float(line.split()[1]) / 1024.0
    except OSError:
        pass
    return 0.0


class _ScriptedChat:
    """Deterministic stand-in for ``swarm.llm.chat_auto`` (the seam the
    offline tests already use); answers every prompt in one call."""

    async def __call__(self, request: Any) -> Any:
        from swarm.llm import ChatResponse, Usage

        return ChatResponse(
            content=SCRIPTED_CONTENT,
            model=request.model,
            provider="scripted",
            usage=Usage(prompt_tokens=11, completion_tokens=7),
        )


@contextmanager
def _patched_chat_auto():
    import swarm.llm as llm_mod

    original = llm_mod.chat_auto
    llm_mod.chat_auto = _ScriptedChat()  # ty: ignore[invalid-assignment]
    try:
        yield
    finally:
        llm_mod.chat_auto = original  # type: ignore[assignment]


def _run_wave(tasks: list[Any]) -> dict[str, Any]:
    """Bench suite through the wave scheduler (WorkerAgent), in-process."""
    from swarm.agents import WorkerAgent

    async def drive() -> tuple[int, int, float]:
        steps_ok = 0
        tasks_ok = 0
        started = time.perf_counter()
        for task in tasks:
            agent = WorkerAgent(plan=task.plan(), model="stub", name=f"wave-{task.id}")
            output = await agent.run(task.prompt)
            steps_ok += len(output.steps_taken)
            if output.steps_taken:
                tasks_ok += 1
        return tasks_ok, steps_ok, time.perf_counter() - started

    with _patched_chat_auto():
        tasks_ok, steps_ok, wall = asyncio.run(drive())
    return {"tasks_ok": tasks_ok, "steps_ok": steps_ok, "wall_s": wall}


def _run_langgraph(
    tasks: list[Any],
    run_plan_langgraph: Any,
    worker_agent_cls: Any,
    plan_cls: Any,
) -> dict[str, Any]:
    """Bench suite through the LangGraph engine with the same scripted chat.

    The engine's worker factory builds one single-step ``WorkerAgent`` per
    step (the factory contract: fresh agent per node attempt).
    """

    def factory(step: Any) -> Any:
        single = plan_cls(steps=[step], route="answer")
        return worker_agent_cls(plan=single, model="stub", name=f"lg-{step.title}")

    steps_ok = 0
    tasks_ok = 0
    started = time.perf_counter()
    with _patched_chat_auto():
        for task in tasks:
            result = run_plan_langgraph(task.plan(), factory)
            steps_ok += len(result.outputs)
            if len(result.outputs) == len(task.plan().steps):
                tasks_ok += 1
    return {
        "tasks_ok": tasks_ok,
        "steps_ok": steps_ok,
        "wall_s": time.perf_counter() - started,
    }
