"""Per-agent YAML manifests under Agents/{Name}/agent.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from swarm_sdk.model_select import ThinkLevel

LangGraphNode = Literal["researcher", "coder", "reviewer"] | None


class AgentTaskSpec(BaseModel):
    id: str
    description: str
    outputs: list[str] = Field(default_factory=list)


class TokenBudgetSpec(BaseModel):
    max_prompt: int = Field(default=2048, ge=1)
    max_completion: int = Field(default=512, ge=1)


class AgentManifest(BaseModel):
    version: int = 1
    name: str
    role: str
    langgraph_node: LangGraphNode = None
    think_level: ThinkLevel = "medium"
    model: str | None = None
    token_budget: TokenBudgetSpec = Field(default_factory=TokenBudgetSpec)
    tasks: list[AgentTaskSpec] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)


def agents_root(start: Path | None = None) -> Path:
    root = start or Path.cwd()
    if (root / "Agents").is_dir():
        return root / "Agents"
    if (root.parent / "Agents").is_dir():
        return root.parent / "Agents"
    return root / "Agents"


def load_agent_manifest(path: Path) -> AgentManifest:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"agent manifest must be a mapping: {path}")
    return AgentManifest.model_validate(data)


def load_all_agent_manifests(agents_dir: Path | None = None) -> dict[str, AgentManifest]:
    base = agents_dir or agents_root()
    out: dict[str, AgentManifest] = {}
    for path in sorted(base.glob("*/agent.yaml")):
        manifest = load_agent_manifest(path)
        out[manifest.name] = manifest
    return out


def langgraph_manifests(manifests: dict[str, AgentManifest]) -> dict[str, AgentManifest]:
    by_node: dict[str, AgentManifest] = {}
    for manifest in manifests.values():
        if manifest.langgraph_node:
            by_node[manifest.langgraph_node] = manifest
    return by_node
