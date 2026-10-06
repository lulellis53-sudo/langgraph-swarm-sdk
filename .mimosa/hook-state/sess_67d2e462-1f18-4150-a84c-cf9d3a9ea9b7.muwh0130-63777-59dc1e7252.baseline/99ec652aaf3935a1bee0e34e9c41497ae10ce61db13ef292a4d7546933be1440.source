"""Per-agent YAML manifests under Agents/{Name}/agent.yaml.

A manifest is the machine-readable half of an agent persona (the other half is
the role contract in the same folder's ``AGENTS.md``). It pre-selects the
model, thinking profile, token budget, and API-key source so the orchestration
engine never has to guess — and so secrets stay out of the repo: ``api_key_env``
names an environment variable; the key value itself is never stored here.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from swarm_sdk.models.selection import ThinkLevel

#: Nodes of the handoff swarm in swarm_sdk.core.swarm; ``None`` means the agent
#: participates only through the orchestration engine, not the handoff graph.
LangGraphNode = Literal["researcher", "coder", "reviewer"] | None


@lru_cache(maxsize=32)
def role_contract(agents_root: str, name: str) -> str:
    """Role contract text (``Agents/{Name}/AGENTS.md``), cached per process.

    The result is cached because the contract is immutable during a run and is
    the system prompt of every step that agent executes — reloading it per
    step would be pure I/O overhead.

    Args:
        agents_root: Absolute path to the directory containing ``{Name}/AGENTS.md``.
        name: Agent (directory) name, e.g. ``"Coder"``.

    Returns:
        The file content as text; ``""`` when the file does not exist (the
        manifest's ``role`` field is then used as the system prompt instead).
    """
    path = Path(agents_root) / name / "AGENTS.md"
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


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


class AgentManifestLoader:
    """Load and index agent manifests from the ``Agents/`` tree."""

    @staticmethod
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

    @staticmethod
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

    @staticmethod
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

    @staticmethod
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
    skip = {"tests", "benchmark"}
    out: dict[str, AgentManifest] = {}
    for path in sorted(base.glob("*/agent.yaml")):
        if path.parent.name in skip:
            continue
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
