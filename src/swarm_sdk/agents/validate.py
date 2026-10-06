"""Validate ``agent.yaml`` files against ``Agents/coordination.yaml``."""

from __future__ import annotations

import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import yaml

from swarm_sdk.agents.manifest import (
    AgentManifest,
    AgentManifestLoader,
    load_all_agent_manifests,
)


def _load_coordination(agents_dir: Path) -> tuple[dict[str, Any] | None, list[str]]:
    """Read ``coordination.yaml``; return ``(data, [])`` or ``(None, [error])``."""
    coord_path = agents_dir / "coordination.yaml"
    if not coord_path.is_file():
        return None, [f"missing {coord_path}"]
    data = yaml.safe_load(coord_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return None, ["coordination.yaml must be a mapping"]
    if not isinstance(data.get("agents", []), list):
        return None, ["coordination.yaml agents must be a list"]
    return data, []


def _check_agent_entries(
    agents: list[Any],
    manifests: Mapping[str, AgentManifest],
    repo_root: Path,
    missing_agent: Callable[[str], str],
) -> list[str]:
    """Check each coordination agent against its manifest path and loaded manifests."""
    errors: list[str] = []
    for entry in agents:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str):
            continue
        manifest_path = entry.get("manifest")
        if isinstance(manifest_path, str) and not (repo_root / manifest_path).is_file():
            errors.append(f"{name}: manifest not found: {manifest_path}")
        if name not in manifests:
            errors.append(missing_agent(name))
        elif manifests[name].name != name:
            errors.append(f"{name}: manifest name mismatch ({manifests[name].name})")
    return errors


def _check_task_entry(entry: dict[str, Any], manifests: Mapping[str, AgentManifest]) -> list[str]:
    """Check one coordination task: assigned agents must exist and know the task."""
    task_id = entry.get("id", "<unknown>")
    assigned = entry.get("assigned", [])
    if not isinstance(assigned, list):
        return [f"{task_id}: assigned must be a list"]
    errors: list[str] = []
    for name in assigned:
        manifest = manifests.get(name) if isinstance(name, str) else None
        if manifest is None:
            errors.append(f"{task_id}: unknown assigned agent {name!r}")
            continue
        task_name = entry.get("task")
        if task_name and task_name not in {task.id for task in manifest.tasks}:
            errors.append(f"{task_id}: unknown task {task_name!r} for agent {name!r}")
    return errors


class AgentValidator:
    """Cross-check coordination entries and on-disk agent manifests."""

    @staticmethod
    def validate_coordination(agents_dir: Path) -> list[str]:
        """Return human-readable errors; empty list means OK.

        Args:
            agents_dir: Path to the ``Agents`` folder.

        Returns:
            Validation error messages (empty if valid).
        """
        data, errors = _load_coordination(agents_dir)
        if data is None:
            return errors
        return _check_agent_entries(
            data.get("agents", []),
            AgentManifestLoader.load_all(agents_dir),
            agents_dir.parent,
            lambda name: f"{name}: missing Agents/{name}/agent.yaml",
        )


def validate_coordination(agents_dir: Path) -> list[str]:
    """Like :meth:`AgentValidator.validate_coordination`, and also check ``tasks`` entries."""
    data, errors = _load_coordination(agents_dir)
    if data is None:
        return errors

    manifests = load_all_agent_manifests(agents_dir)
    errors = _check_agent_entries(
        data.get("agents", []),
        manifests,
        agents_dir.parent,
        lambda name: f"{name}: missing agent.yaml",
    )

    tasks = data.get("tasks", [])
    if not isinstance(tasks, list):
        return [*errors, "coordination.yaml tasks must be a list"]
    for entry in tasks:
        if isinstance(entry, dict):
            errors.extend(_check_task_entry(entry, manifests))
    return errors


def main() -> int:
    """CLI entry for ``python -m swarm_sdk.agents.validate``.

    Returns:
        Process exit code (0 success, 1 on validation errors).
    """
    agents_dir = AgentManifestLoader.agents_root()
    errors = AgentValidator.validate_coordination(agents_dir)
    if errors:
        for line in errors:
            print(line, file=sys.stderr)
        return 1
    print(f"OK: {len(AgentManifestLoader.load_all())} agent manifests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
