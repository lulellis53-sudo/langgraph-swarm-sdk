"""Swarm assembly on top of ``langgraph_swarm.create_swarm``.

``create_swarm`` connects the agents through a supervisor node that routes
to whichever agent is currently active and records handoffs in graph state.
"""

__lazy_modules__ = ["langswarm.agents", "langgraph_swarm"]

from dataclasses import dataclass

from langgraph_swarm import create_swarm

from langswarm.agents import AgentSpec, build_agent
from langswarm.blueprint import SwarmBlueprint
from langswarm.memory import build_checkpointer


@dataclass(slots=True)
class SwarmSpec:
    """Declarative description of a whole swarm."""

    agents: tuple[AgentSpec, ...]
    default_active_agent: str | None = None
    checkpointer: str = "memory"


def build_swarm(spec: SwarmSpec):
    """Build and compile a swarm graph, ready for ``invoke``/``stream``."""
    agents = [build_agent(agent_spec) for agent_spec in spec.agents]
    default_active = spec.default_active_agent or spec.agents[0].name
    graph = create_swarm(agents, default_active_agent=default_active)
    return graph.compile(checkpointer=build_checkpointer(spec.checkpointer))


def build_from_blueprint(blueprint: SwarmBlueprint):
    """Build a compiled swarm graph from a validated YAML/JSON blueprint."""
    specs = tuple(
        AgentSpec(
            name=agent.name,
            system_prompt=agent.system_prompt,
            model=agent.model,
            tools=tuple(agent.tools),
            can_transfer_to=tuple(agent.can_transfer_to),
            handoff_descriptions=dict(agent.handoff_descriptions),
        )
        for agent in blueprint.agents
    )
    return build_swarm(
        SwarmSpec(
            agents=specs,
            default_active_agent=blueprint.default_active_agent,
            checkpointer=blueprint.checkpointer,
        )
    )


compile_swarm_from_blueprint = build_from_blueprint


def build_from_agents_catalog(
    agents_dir: str | None = None,
    agent_names: list[str] | None = None,
    default_active_agent: str = "Orchestrator",
    checkpointer: str = "memory",
):
    """Build a compiled LangGraph swarm directly from Swarm/Agents/ personas."""
    from langswarm.blueprint import load_from_agents_catalog

    blueprint = load_from_agents_catalog(
        agents_dir=agents_dir,
        agent_names=agent_names,
        default_active_agent=default_active_agent,
        checkpointer=checkpointer,
    )
    return build_from_blueprint(blueprint)

