"""LangGraph Server graph factories referenced by ``langgraph.json``.

LangGraph Server imports this file and calls each factory with no arguments to
obtain the compiled graphs it serves:

```json
{
  "dependencies": ["."],
  "graphs": {
    "swarm": "./src/swarm_sdk/serving/graphs.py:swarm_graph",
    "plan": "./src/swarm_sdk/serving/graphs.py:plan_graph"
  }
}
```

All configuration comes from the environment (``SWARM_*`` prefix, see
:mod:`swarm_sdk.agents.config.settings`); no secrets are read here. Start a local
server with ``langgraph dev`` (or deploy with ``langgraph up``) from the repo
root and call it with :func:`swarm_sdk.serving.client.run_on_server`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NotRequired, TypedDict, cast

from langgraph.graph import END, START, StateGraph

from swarm_sdk.agents.config.loader import load_swarm_config
from swarm_sdk.agents.manifest import load_all_agent_manifests
from swarm_sdk.orchestrator.graph import run_plan
from swarm_sdk.orchestrator.plan import Plan, PlanResult
from swarm_sdk.orchestrator.spawn import make_factory, spawn

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel
    from langgraph.graph.state import CompiledStateGraph

    from swarm_sdk.retrieval.cache import SemanticCache


def swarm_graph() -> CompiledStateGraph:
    """Compiled manifest-driven handoff swarm (checkpointer per ``Settings``).

    Returns:
        The graph served under the ``swarm`` id: input
        ``{"messages": [...], "active_agent": ...}``, state carries the
        transcript and the active specialist.
    """
    from swarm_sdk.core.swarm import SwarmSDK

    return cast("CompiledStateGraph", SwarmSDK.from_settings().compiled_graph())


class _PlanGraphState(TypedDict):
    """State of the plan → execute server graph.

    Attributes:
        goal: The free-text goal being decomposed.
        plan: The validated plan (set by the ``plan`` node).
        result: The executed plan outcome (set by the ``execute`` node).
    """

    goal: str
    plan: NotRequired[Plan | None]
    result: NotRequired[dict[str, Any] | None]


def plan_graph(
    *,
    model_override: BaseChatModel | None = None,
    cache: SemanticCache | None = None,
) -> CompiledStateGraph:
    """Two-node graph: decompose a goal into a plan, then run its waves.

    Args:
        model_override: Optional pre-built chat model for the planner and the
            workers (tests); ``None`` loads each manifest's own model.
        cache: Optional semantic cache shared by the workers.

    Returns:
        The graph served under the ``plan`` id: input ``{"goal": ...}``, final
        state carries ``plan`` and a ``result`` payload of the executed plan.
    """

    async def plan_node(state: _PlanGraphState) -> dict[str, Any]:
        plan = await spawn(
            state["goal"],
            load_all_agent_manifests(),
            model_override=model_override,
        )
        return {"goal": state["goal"], "plan": plan}

    async def execute_node(state: _PlanGraphState) -> dict[str, Any]:
        plan = state.get("plan")
        if plan is None:
            raise ValueError("execute node reached without a plan")
        factory = make_factory(
            load_all_agent_manifests(), cache=cache, model_override=model_override
        )
        max_concurrency = load_swarm_config().parallelism.max_concurrency
        result: PlanResult = await run_plan(plan, factory, max_concurrency=max_concurrency)
        return {
            "goal": state["goal"],
            "plan": plan,
            "result": result.model_dump(mode="json"),
        }

    # ty cannot narrow typing.TypedDict to langgraph's TypedDictLike protocol —
    # the same limitation langgraph documents in its own typing module
    # (cf. swarm_sdk.orchestrator.graph.build_graph).
    graph: StateGraph = StateGraph(_PlanGraphState)  # ty: ignore[invalid-argument-type]
    graph.add_node("plan", plan_node)
    graph.add_node("execute", execute_node)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "execute")
    graph.add_edge("execute", END)
    return graph.compile()


__all__ = ["plan_graph", "swarm_graph"]
