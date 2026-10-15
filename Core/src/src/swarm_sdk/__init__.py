"""LangGraph swarm SDK with memory, reranking, token budgets, and semantic cache.

Heavy imports (pydantic_settings, langchain) are deferred to first attribute
access so ``import swarm_sdk`` stays fast for CLI tools and tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = [
    "CODER_PROMPT",
    "RESEARCHER_PROMPT",
    "REVIEWER_PROMPT",
    "RerankFn",
    "ROUTER_SYSTEM",
    "EmbedFn",
    "JevRouter",
    "Plan",
    "PlanResult",
    "PlanStep",
    "RunResult",
    "SearchFn",
    "Settings",
    "StepOutput",
    "SwarmSDK",
    "create_handoff_tool",
    "manifest_node_prompt",
    "parse_task_command",
    "plan_graph",
    "resolve_task",
    "run_plan",
    "run_task_command",
    "swarm_graph",
]
__version__ = "0.1.0"

if TYPE_CHECKING:
    from swarm_sdk.config.settings import Settings
    from swarm_sdk.core.jev_router import JevRouter
    from swarm_sdk.core.prompts import (
        CODER_PROMPT,
        RESEARCHER_PROMPT,
        REVIEWER_PROMPT,
        ROUTER_SYSTEM,
        manifest_node_prompt,
    )
    from swarm_sdk.core.swarm import RunResult, SwarmSDK
    from swarm_sdk.protocols import EmbedFn, RerankFn, SearchFn
    from swarm_sdk.orchestrator.graph import run_plan
    from swarm_sdk.orchestrator.plan import Plan, PlanResult, PlanStep, StepOutput
    from swarm_sdk.orchestrator.task_command import (
        parse_task_command,
        resolve_task,
        run_task_command,
    )
    from swarm_sdk.server.graphs import plan_graph, swarm_graph

_LAZY: dict[str, tuple[str, str]] = {
    "Settings": ("swarm_sdk.config.settings", "Settings"),
    "SwarmSDK": ("swarm_sdk.core.swarm", "SwarmSDK"),
    "RunResult": ("swarm_sdk.core.swarm", "RunResult"),
    "SearchFn": ("swarm_sdk.protocols", "SearchFn"),
    "EmbedFn": ("swarm_sdk.protocols", "EmbedFn"),
    "RerankFn": ("swarm_sdk.protocols", "RerankFn"),
    "JevRouter": ("swarm_sdk.core.jev_router", "JevRouter"),
    "Plan": ("swarm_sdk.orchestrator.plan", "Plan"),
    "PlanStep": ("swarm_sdk.orchestrator.plan", "PlanStep"),
    "StepOutput": ("swarm_sdk.orchestrator.plan", "StepOutput"),
    "PlanResult": ("swarm_sdk.orchestrator.plan", "PlanResult"),
    "run_plan": ("swarm_sdk.orchestrator.graph", "run_plan"),
    "plan_graph": ("swarm_sdk.server.graphs", "plan_graph"),
    "swarm_graph": ("swarm_sdk.server.graphs", "swarm_graph"),
    "parse_task_command": ("swarm_sdk.orchestrator.task_command", "parse_task_command"),
    "resolve_task": ("swarm_sdk.orchestrator.task_command", "resolve_task"),
    "run_task_command": ("swarm_sdk.orchestrator.task_command", "run_task_command"),
    "CODER_PROMPT": ("swarm_sdk.core.prompts", "CODER_PROMPT"),
    "REVIEWER_PROMPT": ("swarm_sdk.core.prompts", "REVIEWER_PROMPT"),
    "RESEARCHER_PROMPT": ("swarm_sdk.core.prompts", "RESEARCHER_PROMPT"),
    "ROUTER_SYSTEM": ("swarm_sdk.core.prompts", "ROUTER_SYSTEM"),
    "manifest_node_prompt": ("swarm_sdk.core.prompts", "manifest_node_prompt"),
}


def create_handoff_tool(agent_name: str, description: str = ""):
    """Create a LangGraph Swarm handoff tool transferring execution to agent_name."""
    from langgraph_swarm import create_handoff_tool as _create_tool

    return _create_tool(
        agent_name=agent_name,
        name=f"transfer_to_{agent_name}",
        description=description,
    )


def __getattr__(name: str) -> Any:
    """Lazy-import public names on first access."""
    if name in _LAZY:
        module_path, attr = _LAZY[name]
        from importlib import import_module

        module = import_module(module_path)
        value = getattr(module, attr)
        # Cache on the module so subsequent lookups skip __getattr__.
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
