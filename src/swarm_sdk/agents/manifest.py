"""Per-agent YAML manifests under Agents/{Name}/agent.yaml.

A manifest is the machine-readable half of an agent persona (the other half is
the role contract in the same folder's ``AGENTS.md``). It pre-selects the
model, thinking profile, token budget, and API-key source so the orchestration
engine never has to guess — and so secrets stay out of the repo: ``api_key_env``
names an environment variable; the key value itself is never stored here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from swarm_sdk.model_select import ThinkLevel

#: Nodes of the fixed handoff swarm in swarm_sdk.swarm; ``None`` means the agent
#: participates only through the orchestration engine, not the handoff graph.
LangGraphNode = Literal["researcher", "coder", "reviewer"] | None


class AgentTaskSpec(BaseModel):
    """One task type the agent can be assigned.

    Attributes:
        id: Stable task identifier, e.g. ``"implement_feature"``.
        description: What the task means and when it is assigned.
        outputs: Names of the artifacts the agent commits to producing.
    """

    id: str
    description: str
    outputs: list[str] = Field(default_factory=list)


class TokenBudgetSpec(BaseModel):
    """Hard per-call token caps for the agent.

    Attributes:
        max_prompt: Maximum tokens for system + user prompt combined. The
            engine's TokenBudget packs and truncates to this cap.
        max_completion: Requested maximum for the model's answer.
    """

    max_prompt: int = Field(default=2048, ge=1)
    max_completion: int = Field(default=512, ge=1)


class AgentManifest(BaseModel):
    """Validated ``agent.yaml`` for one agent persona.

    Attributes:
        version: Manifest schema version (currently always ``1``).
        name: Agent name; matches the directory under ``Agents/``.
        role: One-line role summary; fallback system prompt when no AGENTS.md.
        langgraph_node: Handoff-graph node for this agent, if any.
        think_level: Default reasoning depth (PEP 484 Literal set from
            :data:`ThinkLevel`): off, low, medium, high, xhigh.
        effort: Optional provider reasoning-effort hint (low/medium/high);
            ``None`` leaves the provider default in place.
        model: LangChain ``init_chat_model`` string, e.g. ``"openai:gpt-4o"``.
        api_key_env: Name of the environment variable holding the provider API
            key for this agent. The secret value never lives in the manifest.
        token_budget: Per-call token caps.
        tasks: Task types this agent accepts.
        capabilities: Capability tags used for routing decisions.
    """

    version: int = 1
    name: str
    role: str
    langgraph_node: LangGraphNode = None
    think_level: ThinkLevel = "medium"
    effort: str | None = Field(
        default=None,
        pattern="^(low|medium|high)$",
        description="Reasoning effort hint passed to the provider when supported.",
    )
    model: str | None = None
    api_key_env: str | None = Field(
        default=None,
        description="Name of the environment variable holding the provider API key "
        "(the secret value itself never lives in the manifest).",
    )
    token_budget: TokenBudgetSpec = Field(default_factory=TokenBudgetSpec)
    tasks: list[AgentTaskSpec] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)


def agents_root(start: Path | None = None) -> Path:
    """Locate the ``Agents/`` directory from a starting path.

    Checks ``start`` and its parent so callers running from a subdirectory
    (or from ``src/``) still resolve the repo's agent personas.

    Args:
        start: Directory to search from; defaults to the current working directory.

    Returns:
        The ``Agents`` path when found (in ``start`` or its parent), else
        ``start / "Agents"`` as a best-effort default.
    """
    root = start or Path.cwd()
    if (root / "Agents").is_dir():
        return root / "Agents"
    if (root.parent / "Agents").is_dir():
        return root.parent / "Agents"
    return root / "Agents"


def load_agent_manifest(path: Path) -> AgentManifest:
    """Parse and validate one ``agent.yaml`` file.

    Args:
        path: Path to the manifest file.

    Returns:
        The validated manifest.

    Raises:
        ValueError: When the YAML top level is not a mapping.
        pydantic.ValidationError: When fields fail validation.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"agent manifest must be a mapping: {path}")
    return AgentManifest.model_validate(data)


def load_all_agent_manifests(agents_dir: Path | None = None) -> dict[str, AgentManifest]:
    """Load every ``Agents/{Name}/agent.yaml`` manifest.

    Args:
        agents_dir: Directory containing the per-agent folders; defaults to
            the resolved :func:`agents_root`.

    Returns:
        Manifests keyed by agent name, sorted by directory name for
        deterministic ordering.
    """
    base = agents_dir or agents_root()
    out: dict[str, AgentManifest] = {}
    for path in sorted(base.glob("*/agent.yaml")):
        manifest = load_agent_manifest(path)
        out[manifest.name] = manifest
    return out


def langgraph_manifests(manifests: dict[str, AgentManifest]) -> dict[str, AgentManifest]:
    """Index manifests that are wired into the handoff graph.

    Args:
        manifests: All loaded manifests, keyed by name.

    Returns:
        The subset having a non-``None`` ``langgraph_node``, keyed by node name
        (researcher/coder/reviewer).
    """
    by_node: dict[str, AgentManifest] = {}
    for manifest in manifests.values():
        if manifest.langgraph_node:
            by_node[manifest.langgraph_node] = manifest
    return by_node
