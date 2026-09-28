"""LangGraph execution of a Plan: one node per wave, parallel steps inside a wave.

Each wave is a node in a linear StateGraph (wave barriers are the dependency
frontier). Steps inside a wave are dispatched with asyncio.gather, so they run
concurrently — under uvloop with free-threaded Python 3.14 the blocking provider
calls also parallelize across the runtime thread pool.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from typing_extensions import TypedDict

from langgraph.graph import END, StateGraph

from .plan import Plan, PlanResult, PlanStep, StepOutput, UsageTotals
from .worker import WorkerAgent

WorkerFactory = Callable[[PlanStep], WorkerAgent]


class PlanState(TypedDict):
    outputs: dict[str, StepOutput]
    usage: UsageTotals


def _dep_outputs(step: PlanStep, state: PlanState) -> dict[str, str]:
    wanted = step.inputs or step.depends_on
    return {
        dep: state["outputs"][dep].content
        for dep in wanted
        if dep in state["outputs"] and state["outputs"][dep].status == "ok"
    }


async def _run_wave(
    steps: list[PlanStep],
    factory: WorkerFactory,
    state: PlanState,
) -> None:
    async def one(step: PlanStep) -> StepOutput:
        worker = factory(step)
        return await worker.run(step.id, step.description, _dep_outputs(step, state))

    results = await asyncio.gather(*(one(s) for s in steps))
    for out in results:
        state["outputs"][out.step_id] = out
        if out.cached:
            state["usage"].cached_calls += 1
        else:
            state["usage"].llm_calls += 1
            state["usage"].prompt_tokens += out.prompt_tokens
            state["usage"].completion_tokens += out.completion_tokens


def build_graph(plan: Plan, factory: WorkerFactory) -> StateGraph:
    graph = StateGraph(PlanState)
    waves = plan.waves()
    for index, steps in enumerate(waves):

        async def node(state: PlanState, _steps: list[PlanStep] = steps) -> PlanState:
            await _run_wave(_steps, factory, state)
            return state

        graph.add_node(f"wave_{index}", node)
    for index in range(len(waves)):
        if index == 0:
            graph.set_entry_point("wave_0")
        if index == len(waves) - 1:
            graph.add_edge(f"wave_{index}", END)
        else:
            graph.add_edge(f"wave_{index}", f"wave_{index + 1}")
    return graph


async def run_plan(plan: Plan, factory: WorkerFactory) -> PlanResult:
    """Execute the plan through LangGraph; returns per-step outputs + usage totals."""
    graph = build_graph(plan, factory)
    compiled = graph.compile()
    started = time.perf_counter()
    final = await compiled.ainvoke({"outputs": {}, "usage": UsageTotals()})
    result = PlanResult(outputs=final["outputs"], usage=final["usage"])
    result.usage.wall_s = time.perf_counter() - started
    return result
