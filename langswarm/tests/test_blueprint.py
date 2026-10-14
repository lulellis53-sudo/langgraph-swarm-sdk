"""Tests for YAML blueprint parsing and msgspec schema validation."""

from __future__ import annotations

from pathlib import Path

import msgspec
import pytest

from langswarm.blueprint import SwarmBlueprint, load_blueprint


def test_load_valid_blueprint() -> None:
    """Test loading the official 12-agent swarm.yaml blueprint."""
    config_path = Path(__file__).parent.parent / "config" / "swarm.yaml"
    assert config_path.is_file(), f"Config file not found at {config_path}"

    blueprint = load_blueprint(config_path)
    assert isinstance(blueprint, SwarmBlueprint)
    assert blueprint.default_active_agent == "Router"
    assert blueprint.checkpointer == "memory"
    assert len(blueprint.agents) == 12

    # Validate specific agents
    agent_names = {a.name for a in blueprint.agents}
    expected = {
        "Router", "Researcher", "Archivist", "Writer", "Coder", "Reviewer",
        "Analyst", "WebScout", "MemoryKeeper", "Historian", "BenchmarkRunner", "Finisher"
    }
    assert expected.issubset(agent_names)

    # Validate Router handoff mappings
    router = next(a for a in blueprint.agents if a.name == "Router")
    assert len(router.can_transfer_to) == 11
    assert "Coder" in router.can_transfer_to
    assert router.handoff_descriptions.get("Coder") is not None


def test_invalid_blueprint_validation() -> None:
    """Test validation errors on missing required fields in blueprint."""
    invalid_yaml = """
agents:
  - name: IncompleteAgent
"""
    with pytest.raises(msgspec.DecodeError):
        msgspec.yaml.decode(invalid_yaml.encode("utf-8"), type=SwarmBlueprint)
