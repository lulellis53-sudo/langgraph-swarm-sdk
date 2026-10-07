"""Characterization tests for ``swarm_sdk.agents.validate`` (both validators)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from swarm_sdk.agents.validate import AgentValidator, validate_coordination


def _agent(
    agents: Path, name: str, tasks: tuple[str, ...] = ("t1",), *, yaml_name: str | None = None
):
    folder = agents / name
    folder.mkdir(parents=True)
    manifest = {
        "name": yaml_name or name,
        "role": "tester",
        "tasks": [{"id": task, "description": "d"} for task in tasks],
    }
    (folder / "agent.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")


def _coordination(agents: Path, data: object) -> None:
    (agents / "coordination.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")


@pytest.fixture
def agents(tmp_path: Path) -> Path:
    path = tmp_path / "Agents"
    path.mkdir()
    return path


@pytest.mark.parametrize("validate", [AgentValidator.validate_coordination, validate_coordination])
class TestShared:
    def test_missing_file(self, agents: Path, validate) -> None:
        assert validate(agents) == [f"missing {agents / 'coordination.yaml'}"]

    def test_top_level_must_be_mapping(self, agents: Path, validate) -> None:
        _coordination(agents, ["x"])
        assert validate(agents) == ["coordination.yaml must be a mapping"]

    def test_agents_must_be_a_list(self, agents: Path, validate) -> None:
        _coordination(agents, {"agents": {"a": 1}})
        assert validate(agents) == ["coordination.yaml agents must be a list"]

    def test_valid_agent_has_no_errors(self, agents: Path, validate) -> None:
        _agent(agents, "Coder")
        _coordination(
            agents, {"agents": [{"name": "Coder", "manifest": "Agents/Coder/agent.yaml"}]}
        )
        assert validate(agents) == []

    def test_missing_manifest_file_and_agent(self, agents: Path, validate) -> None:
        _coordination(
            agents, {"agents": [{"name": "Ghost", "manifest": "Agents/Ghost/agent.yaml"}]}
        )
        errors = validate(agents)
        assert errors[0] == "Ghost: manifest not found: Agents/Ghost/agent.yaml"
        assert len(errors) == 2 and errors[1].startswith("Ghost: missing ")

    def test_non_dict_and_nameless_entries_are_skipped(self, agents: Path, validate) -> None:
        _coordination(agents, {"agents": ["str", {"manifest": "x"}, {"name": 3}]})
        assert validate(agents) == []


def test_missing_message_wording_differs_per_validator(agents: Path) -> None:
    _coordination(agents, {"agents": [{"name": "Ghost"}]})
    assert AgentValidator.validate_coordination(agents) == [
        "Ghost: missing Agents/Ghost/agent.yaml"
    ]
    assert validate_coordination(agents) == ["Ghost: missing agent.yaml"]


class TestTasks:
    def test_tasks_must_be_a_list(self, agents: Path) -> None:
        _agent(agents, "Coder")
        _coordination(agents, {"agents": [{"name": "Coder"}], "tasks": {"a": 1}})
        assert validate_coordination(agents) == ["coordination.yaml tasks must be a list"]

    def test_tasks_error_keeps_earlier_agent_errors(self, agents: Path) -> None:
        _coordination(agents, {"agents": [{"name": "Ghost"}], "tasks": "nope"})
        assert validate_coordination(agents) == [
            "Ghost: missing agent.yaml",
            "coordination.yaml tasks must be a list",
        ]

    def test_assigned_must_be_a_list(self, agents: Path) -> None:
        _coordination(agents, {"tasks": [{"id": "T1", "assigned": "Coder"}]})
        assert validate_coordination(agents) == ["T1: assigned must be a list"]

    def test_unknown_agent_and_unknown_task(self, agents: Path) -> None:
        _agent(agents, "Coder", tasks=("known",))
        _coordination(
            agents,
            {
                "agents": [{"name": "Coder"}],
                "tasks": [
                    {"id": "T1", "assigned": ["Nobody", 7]},
                    {"id": "T2", "assigned": ["Coder"], "task": "known"},
                    {"id": "T3", "assigned": ["Coder"], "task": "other"},
                    {"assigned": ["Coder"]},
                    "skip-me",
                ],
            },
        )
        assert validate_coordination(agents) == [
            "T1: unknown assigned agent 'Nobody'",
            "T1: unknown assigned agent 7",
            "T3: unknown task 'other' for agent 'Coder'",
        ]


def test_manifest_registered_under_its_own_name_makes_the_folder_name_missing(agents: Path) -> None:
    """Manifests are keyed by their ``name`` field, so a renamed manifest reads as missing."""
    _agent(agents, "Coder", yaml_name="Other")
    _coordination(agents, {"agents": [{"name": "Coder"}]})
    assert AgentValidator.validate_coordination(agents) == [
        "Coder: missing Agents/Coder/agent.yaml"
    ]
    assert validate_coordination(agents) == ["Coder: missing agent.yaml"]
