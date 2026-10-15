"""YAML blueprint parsing and schema validation."""

from pathlib import Path

import msgspec
import pytest

from langswarm.blueprint import SwarmBlueprint, load_blueprint


def test_load_valid_blueprint() -> None:
    config_path = Path(__file__).parents[1] / "config" / "swarm.yaml"
    blueprint = load_blueprint(config_path)
    assert isinstance(blueprint, SwarmBlueprint)
    assert blueprint.default_active_agent == "Router"
    assert blueprint.checkpointer == "memory"
    assert len(blueprint.agents) == 13
    names = {agent.name for agent in blueprint.agents}
    assert {"Router", "Researcher", "Davinci", "Finisher"} <= names
    router = next(agent for agent in blueprint.agents if agent.name == "Router")
    assert set(router.can_transfer_to) == names - {"Router"}


def test_invalid_blueprint_validation() -> None:
    with pytest.raises(msgspec.DecodeError):
        msgspec.yaml.decode(b"agents:\n  - name: IncompleteAgent\n", type=SwarmBlueprint)
