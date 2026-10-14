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
