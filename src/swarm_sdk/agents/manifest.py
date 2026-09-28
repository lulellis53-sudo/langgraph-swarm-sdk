"""Per-agent YAML manifests under ``Agents/{Name}/agent.yaml``."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from swarm_sdk.decorators import Static, wrapper
from swarm_sdk.model_select import ThinkLevel

LangGraphNode = Literal["researcher", "coder", "reviewer"] | None


class AgentTaskSpec(BaseModel):
    """One default task listed in an agent manifest."""

    id: str
    description: str
    outputs: list[str] = Field(default_factory=list)


class TokenBudgetSpec(BaseModel):
    """Per-agent prompt and completion caps."""

    max_prompt: int = Field(default=2048, ge=1)
    max_completion: int = Field(default=512, ge=1)


class AgentManifest(BaseModel):
    """Parsed ``agent.yaml`` for a single swarm role."""

    version: int = 1
    name: str
    role: str
    langgraph_node: LangGraphNode = None
    think_level: ThinkLevel = "medium"
    model: str | None = None
    token_budget: TokenBudgetSpec = Field(default_factory=TokenBudgetSpec)
    tasks: list[AgentTaskSpec] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)


class AgentManifestLoader:
    """Load and index agent manifests from the ``Agents/`` tree."""

    @Static
    @wrapper
    def agents_root(start: Path | None = None) -> Path:
        """Resolve the ``Agents`` directory from cwd or a parent.

        Args:
            start: Starting directory; defaults to ``Path.cwd()``.

        Returns:
            Path to the ``Agents`` folder (may not exist yet).
        """
        root = start or Path.cwd()
        if (root / "Agents").is_dir():
            return root / "Agents"
        if (root.parent / "Agents").is_dir():
            return root.parent / "Agents"
        return root / "Agents"

    @Static
    def load_one(path: Path) -> AgentManifest:
        """Load a single manifest file.

        Args:
            path: Path to ``agent.yaml``.

        Returns:
            Validated manifest.

        Raises:
            ValueError: If the file is not a YAML mapping.
        """
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"agent manifest must be a mapping: {path}")
        return AgentManifest.model_validate(data)

    @Static
    def load_all(agents_dir: Path | None = None) -> dict[str, AgentManifest]:
        """Load every ``*/agent.yaml`` under the agents directory.

        Args:
            agents_dir: Override agents root; defaults to :meth:`agents_root`.

        Returns:
            Map of manifest ``name`` to manifest.
        """
        base = agents_dir or AgentManifestLoader.agents_root()
        out: dict[str, AgentManifest] = {}
        for path in sorted(base.glob("*/agent.yaml")):
            manifest = AgentManifestLoader.load_one(path)
            out[manifest.name] = manifest
        return out

    @Static
    @wrapper
    def langgraph_by_node(manifests: dict[str, AgentManifest]) -> dict[str, AgentManifest]:
        """Index manifests that bind a LangGraph specialist node.

        Args:
            manifests: All loaded manifests keyed by name.

        Returns:
            Map of ``langgraph_node`` value to manifest.
        """
        by_node: dict[str, AgentManifest] = {}
        for manifest in manifests.values():
            if manifest.langgraph_node:
                by_node[manifest.langgraph_node] = manifest
        return by_node


def agents_root(start: Path | None = None) -> Path:
    """See :meth:`AgentManifestLoader.agents_root`."""
    return AgentManifestLoader.agents_root(start)


def load_agent_manifest(path: Path) -> AgentManifest:
    """See :meth:`AgentManifestLoader.load_one`."""
    return AgentManifestLoader.load_one(path)


def load_all_agent_manifests(agents_dir: Path | None = None) -> dict[str, AgentManifest]:
    """See :meth:`AgentManifestLoader.load_all`."""
    return AgentManifestLoader.load_all(agents_dir)


def langgraph_manifests(manifests: dict[str, AgentManifest]) -> dict[str, AgentManifest]:
    """See :meth:`AgentManifestLoader.langgraph_by_node`."""
    return AgentManifestLoader.langgraph_by_node(manifests)
