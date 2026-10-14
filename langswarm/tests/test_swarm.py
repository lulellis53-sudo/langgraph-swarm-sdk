"""Tests for compiling and inspecting the 12-agent LangGraph swarm."""

from __future__ import annotations

from pathlib import Path

from langswarm.blueprint import load_blueprint
from langswarm.swarm import compile_swarm_from_blueprint


def test_swarm_compilation() -> None:
    """Test full compilation of the 12-agent swarm from YAML blueprint."""
    config_path = Path(__file__).parent.parent / "config" / "swarm.yaml"
    blueprint = load_blueprint(config_path)

    # Compile the swarm graph
    swarm = compile_swarm_from_blueprint(blueprint)
    assert swarm is not None

    # Verify graph structure contains agents
    nodes = list(swarm.get_graph().nodes.keys())
    assert "Router" in nodes
    assert "Coder" in nodes
    assert "Researcher" in nodes
