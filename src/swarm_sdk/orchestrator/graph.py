"""LangGraph execution of a Plan: one node per wave, parallel steps inside a wave.

Each wave is a node in a linear ``StateGraph`` (wave barriers are the dependency
frontier computed by :meth:`Plan.waves`). Steps inside a wave are dispatched with
:func:`swarm_sdk.models.selection.bounded_gather` so they run concurrently up to
``max_concurrency`` — under uvloop the I/O interleaves, and on free-threaded
Python 3.14 the blocking provider SDK calls also parallelize across the widened
runtime thread pool (see :mod:`swarm_sdk.runtime.executor`).
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

from swarm_sdk.models.selection import bounded_gather

from .plan import Plan, PlanResult, PlanStep, StepOutput, UsageTotals
from .worker import WorkerAgent

# Factory contract: the engine builds one fresh worker per step attempt.
WorkerFactory = Callable[[PlanStep], WorkerAgent]


class PlanState(TypedDict):
    """LangGraph state threaded through the wave nodes.

    Attributes:
        outputs: Completed step outputs keyed by step id.
        usage: Running token/call totals, accumulated wave by wave.
    """

    outputs: dict[str, StepOutput]
    usage: UsageTotals


def _dep_outputs(step: PlanStep, state: PlanState) -> dict[str, str]:
    """Collect the dependency outputs a step declared as its inputs.

    Falls back to ``depends_on`` when the step declared no explicit ``inputs``
    (a step receives everything it waited for, and nothing else — token saving).

    Args:
        step: The step about to run.
        state: Current plan state with completed outputs.

    Returns:
        Mapping of step id → output content, only for declared inputs that
        completed successfully.
    """
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
    *,
    max_concurrency: int,
) -> None:
    """Execute all steps of one wave concurrently and fold results into state.

    Args:
        steps: The wave's steps (mutually independent by construction).
        factory: Builds a fresh worker per step.
        state: Plan state mutated in place; ``outputs`` gains one entry per
            step and ``usage`` accumulates call/token totals.
        max_concurrency: Cap on in-flight steps (``parallelism.max_concurrency``).
    """

    def one_factory(step: PlanStep) -> Callable[[], Awaitable[StepOutput]]:
        async def run_step() -> StepOutput:
            worker = factory(step)
            return await worker.run(
                step.id,
                step.description,
                _dep_outputs(step, state),
                files=step.files,
                task=step.task,
            )

        return run_step

    results = await bounded_gather(
        [one_factory(step) for step in steps],
        max_concurrency=max_concurrency,
    )
    for out in results:
        state["outputs"][out.step_id] = out
        if out.cached:
            state["usage"].cached_calls += 1
        else:
            state["usage"].llm_calls += 1
            state["usage"].prompt_tokens += out.prompt_tokens
            state["usage"].completion_tokens += out.completion_tokens


def build_graph(
    plan: Plan,
    factory: WorkerFactory,
    *,
    max_concurrency: int = 8,
) -> StateGraph:
    """Compile the plan's wave structure into a LangGraph ``StateGraph``.

    The graph is linear: ``wave_0 → wave_1 → … → END``. Parallelism lives
    *inside* each node (bounded gather over the wave's steps), so LangGraph
    provides checkpointable, deterministic wave ordering while the steps within
    a wave race up to ``max_concurrency``.

    Args:
        plan: The validated plan to execute.
        factory: Worker factory used by every wave node.
        max_concurrency: Cap on in-flight steps inside a wave.

    Returns:
        The uncompiled ``StateGraph`` (callers may add checkpointers before
        compiling; :func:`run_plan` compiles directly).
    """
    # ty cannot narrow typing.TypedDict to langgraph's TypedDictLike protocol —
    # the same limitation langgraph documents in its own typing module.
    graph = StateGraph(PlanState)  # ty: ignore[invalid-argument-type]
    waves = plan.waves()
    for index, steps in enumerate(waves):

        async def node(state: PlanState, _steps: list[PlanStep] = steps) -> PlanState:
            # Default-arg binding: captures this wave's steps, not the loop variable.
            await _run_wave(_steps, factory, state, max_concurrency=max_concurrency)
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


async def run_plan(
    plan: Plan,
    factory: WorkerFactory,
    *,
    max_concurrency: int = 8,
) -> PlanResult:
    """Execute the plan through LangGraph and collect outputs + usage totals.

    Args:
        plan: The validated plan to execute.
        factory: Builds a worker per step attempt.
        max_concurrency: Cap on in-flight steps inside a wave (from
            ``parallelism.max_concurrency`` when the caller has file config).

    Returns:
        The plan result: per-step outputs keyed by step id, and aggregated
        usage (prompt/completion tokens, LLM vs cached calls, wall time).
    """
    plan.assert_file_partition()
    graph = build_graph(plan, factory, max_concurrency=max_concurrency)
    compiled = graph.compile()
    started = time.perf_counter()
    final = await compiled.ainvoke({"outputs": {}, "usage": UsageTotals()})
    result = PlanResult(outputs=final["outputs"], usage=final["usage"])
    result.usage.wall_s = time.perf_counter() - started
    return result
