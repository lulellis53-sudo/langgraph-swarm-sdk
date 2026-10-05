"""Smoke tests for the math specialist manifest and handoff schema."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from swarm_sdk.agents.manifest import load_agent_manifest

AGENTS_ROOT = Path(__file__).parent.parent / "Agents"


def test_math_manifest_loads() -> None:
    manifest = load_agent_manifest(AGENTS_ROOT / "math" / "agent.yaml")
    assert manifest.name == "math"
    assert manifest.role == "mathematical_modeling"
    task_ids = {task.id for task in manifest.tasks}
    assert task_ids >= {
        "solve_math",
        "verify_math",
        "numerical_stability_review",
        "verify_with_script",
    }
    assert set(manifest.capabilities) >= {
        "symbolic_math",
        "numerical_verification",
        "hardware_dispatch",
    }


def test_math_handoff_schema_is_valid_json_schema() -> None:
    schema_path = AGENTS_ROOT / "math" / "handoff.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["title"] == "math handoff"
    assert "agent" in schema["required"]
    assert schema["properties"]["agent"]["const"] == "math"
    assert "verify_with_script" in schema["properties"]["task_id"]["enum"]


def test_math_agent_is_registered_in_coordination() -> None:
    coord = yaml.safe_load((AGENTS_ROOT / "coordination.yaml").read_text(encoding="utf-8"))
    names = {entry["name"] for entry in coord.get("agents", []) if isinstance(entry, dict)}
    assert "math" in names
