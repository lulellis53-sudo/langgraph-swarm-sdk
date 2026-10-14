"""Typed, validated swarm blueprints.

Swarm definitions are plain YAML (or JSON) files decoded straight into
msgspec Struct classes, so a malformed configuration fails at load time with
a precise error instead of at graph-construction time.
"""

__lazy_modules__ = ["msgspec"]

import msgspec


class AgentBlueprint(msgspec.Struct, frozen=True):
    """One agent as declared in a swarm file."""

    name: str
    system_prompt: str
    model: str = "openai:gpt-4o"
    tools: list[str] = []
    can_transfer_to: list[str] = []
    handoff_descriptions: dict[str, str] = {}


class SwarmBlueprint(msgspec.Struct, frozen=True):
    """A whole swarm as declared in a swarm file."""

    agents: list[AgentBlueprint]
    default_active_agent: str | None = None
    checkpointer: str = "memory"


def load_blueprint(path: str) -> SwarmBlueprint:
    """Load and validate a swarm definition from YAML or JSON."""
    with open(path, "rb") as handle:
        raw = handle.read()
    if path.endswith((".yaml", ".yml")):
        return msgspec.yaml.decode(raw, type=SwarmBlueprint)
    return msgspec.json.decode(raw, type=SwarmBlueprint)


def load_from_agents_catalog(
    agents_dir: str | None = None,
    agent_names: list[str] | None = None,
    default_active_agent: str = "Orchestrator",
    checkpointer: str = "memory",
) -> SwarmBlueprint:
    """Construct a SwarmBlueprint from canonical personas under Swarm/Agents/.

    Args:
        agents_dir: Root directory of agents (e.g. /Users/usuario/Myworkspace/Swarm/Agents).
        agent_names: Specific agent names to load. Defaults to core personas.
        default_active_agent: Initial active agent (defaults to Orchestrator).
        checkpointer: Persistence engine ('memory', 'sqlite', 'redis').

    Returns:
        Validated SwarmBlueprint instance populated with AGENTS.md role contracts.
    """
    from pathlib import Path
    import yaml

    root = Path(agents_dir) if agents_dir else Path("/Users/usuario/Myworkspace/Swarm/Agents")
    if not root.is_dir():
        # Fallback to relative resolution
        candidate = Path.cwd() / "Agents"
        if candidate.is_dir():
            root = candidate

    target_names = agent_names or [
        "Orchestrator",
        "Coder",
        "Reviewer",
        "Tester",
        "Debugger",
        "Documenter",
        "Architect",
        "Planner",
    ]

    agent_blueprints: list[AgentBlueprint] = []
    available_peers = list(target_names)

    for name in target_names:
        agent_folder = root / name
        manifest_file = agent_folder / "agent.yaml"
        contract_file = agent_folder / "AGENTS.md"

        model = "openai:gpt-4o"
        if manifest_file.is_file():
            try:
                with open(manifest_file, encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                    model = data.get("model", model)
            except Exception:
                pass

        system_prompt = f"You are the {name} agent."
        if contract_file.is_file():
            try:
                system_prompt = contract_file.read_text(encoding="utf-8")
            except Exception:
                pass

        peers = [p for p in available_peers if p != name]
        handoffs = {p: f"Transfer to {p}." for p in peers}

        agent_blueprints.append(
            AgentBlueprint(
                name=name,
                system_prompt=system_prompt,
                model=model,
                tools=[],
                can_transfer_to=peers,
                handoff_descriptions=handoffs,
            )
        )

    active = default_active_agent if default_active_agent in target_names else target_names[0]
    return SwarmBlueprint(
        agents=agent_blueprints,
        default_active_agent=active,
        checkpointer=checkpointer,
    )

