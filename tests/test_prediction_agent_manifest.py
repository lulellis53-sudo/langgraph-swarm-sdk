"""Smoke tests for the Prediction specialist manifest and handoff schema."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from swarm_sdk.agents.manifest import load_agent_manifest

AGENTS_ROOT = Path(__file__).resolve().parents[1] / "Agents"

pytestmark = pytest.mark.skipif(
    not (AGENTS_ROOT / "coordination.yaml").is_file(),
    reason="Agents/ is not in this checkout",
)


def test_prediction_manifest_loads() -> None:
    manifest = load_agent_manifest(AGENTS_ROOT / "Prediction" / "agent.yaml")
    assert manifest.name == "Prediction"
    assert manifest.role == "time_series_forecasting"
    assert {task.id for task in manifest.tasks} == {"forecast", "backtest", "feature_engineering"}


def test_prediction_handoff_schema_is_valid_json_schema() -> None:
    schema_path = AGENTS_ROOT / "Prediction" / "handoff.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["title"] == "Prediction handoff"
    assert "agent" in schema["required"]
    assert schema["properties"]["agent"]["const"] == "Prediction"


def test_prediction_agent_is_registered_in_coordination() -> None:
    coord = yaml.safe_load((AGENTS_ROOT / "coordination.yaml").read_text(encoding="utf-8"))
    names = {entry["name"] for entry in coord.get("agents", []) if isinstance(entry, dict)}
    assert "Prediction" in names
