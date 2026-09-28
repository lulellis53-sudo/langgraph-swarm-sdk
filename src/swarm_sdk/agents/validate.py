"""Validate ``agent.yaml`` files against ``Agents/coordination.yaml``."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from swarm_sdk.agents.manifest import AgentManifestLoader
from swarm_sdk.decorators import Static


class AgentValidator:
    """Cross-check coordination entries and on-disk agent manifests."""

    @Static
    def validate_coordination(agents_dir: Path) -> list[str]:
        """Return human-readable errors; empty list means OK.

        Args:
            agents_dir: Path to the ``Agents`` folder.

        Returns:
            Validation error messages (empty if valid).
        """
        errors: list[str] = []
        repo_root = agents_dir.parent
        coord_path = agents_dir / "coordination.yaml"
        if not coord_path.is_file():
            return [f"missing {coord_path}"]

        data = yaml.safe_load(coord_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return ["coordination.yaml must be a mapping"]

        agents = data.get("agents", [])
        if not isinstance(agents, list):
            return ["coordination.yaml agents must be a list"]

        manifests = AgentManifestLoader.load_all(agents_dir)
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
                errors.append(f"{name}: missing Agents/{name}/agent.yaml")
            elif manifests[name].name != name:
                errors.append(f"{name}: manifest name mismatch ({manifests[name].name})")
        return errors


def validate_coordination(agents_dir: Path) -> list[str]:
    """See :meth:`AgentValidator.validate_coordination`."""
    return AgentValidator.validate_coordination(agents_dir)


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
