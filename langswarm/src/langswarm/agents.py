"""Agent specification and construction.

Each agent is a tool-calling agent built with ``langchain.agents.create_agent``
and wired with ``langgraph_swarm.create_handoff_tool`` for every agent it is
allowed to transfer control to. Tools may be given as callables (programmatic
specs) or as registry names (YAML blueprints).
"""

__lazy_modules__ = ["langchain", "langgraph_swarm"]

from collections.abc import Callable
from dataclasses import dataclass, field

from langchain.agents import create_agent
from langgraph_swarm import create_handoff_tool


@dataclass(slots=True)
class AgentSpec:
    """Declarative description of one swarm agent."""

    name: str
    system_prompt: str
    model: str = "openai:gpt-4o"
    tools: tuple[Callable | str, ...] = ()
    can_transfer_to: tuple[str, ...] = ()
    handoff_descriptions: dict[str, str] = field(default_factory=dict)


def _instantiate(tool: Callable | str) -> Callable:
    if isinstance(tool, str):
        from langswarm.tools import resolve_tools

        return resolve_tools([tool])[0]
    return tool


def build_agent(spec: AgentSpec):
    """Build a tool-calling agent with handoff tools for permitted targets."""
    handoffs = [
        create_handoff_tool(
            agent_name=target,
            description=spec.handoff_descriptions.get(
                target, f"Transfer to {target}."
            ),
        )
        for target in spec.can_transfer_to
    ]
    tools = [_instantiate(tool) for tool in spec.tools]
    return create_agent(
        spec.model,
        tools=[*tools, *handoffs],
        system_prompt=spec.system_prompt,
        name=spec.name,
    )
