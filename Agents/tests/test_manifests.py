"""Agent manifests (Agents/*/agent.yaml) must parse and point at real skill files."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

AGENTS = Path(__file__).resolve().parents[1]


def manifest_paths(root: Path) -> list[Path]:
    """List ``agent.yaml`` files that sit directly inside each agent folder."""
    return sorted(root.glob("*/agent.yaml"))


def load_manifest(path: Path) -> dict:
    """Parse one manifest. Raises ValueError if it is not a mapping."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a YAML mapping")
    return data


def test_load_manifest_rejects_non_mapping(tmp_path: Path) -> None:
    bad = tmp_path / "agent.yaml"
    bad.write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not a YAML mapping"):
        load_manifest(bad)


def test_agents_have_manifests() -> None:
    assert manifest_paths(AGENTS)


@pytest.mark.parametrize("path", manifest_paths(AGENTS), ids=lambda p: p.parent.name)
def test_manifest_has_name(path: Path) -> None:
    assert load_manifest(path).get("name")


@pytest.mark.parametrize("path", manifest_paths(AGENTS), ids=lambda p: p.parent.name)
def test_manifest_skill_files_exist(path: Path) -> None:
    skills = load_manifest(path).get("skills") or []
    missing = [skill for skill in skills if not (path.parent / skill).is_file()]
    assert not missing, f"{path.parent.name}: missing skill files {missing}"
