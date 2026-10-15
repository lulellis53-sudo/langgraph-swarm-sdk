"""Core prompts: router and node system prompts, and the per-manifest node prompt."""

from __future__ import annotations

from typing import TYPE_CHECKING

from swarm_sdk.agents.manifest import (
    AgentManifest,
    role_contract,
)
from swarm_sdk.prompting.budget import TokenBudget

if TYPE_CHECKING:
    pass


ROUTER_SYSTEM = 'Route work. Reply with JSON only: {"mode":"parallel" or "swarm","tasks":[]}.'


RESEARCHER_PROMPT = "You are the researcher. Use only the supplied context. Be brief."


CODER_PROMPT = "You are the coder. Be brief."


REVIEWER_PROMPT = "You are the reviewer. Be brief."


# Fallback one-line prompts for the default trio when no manifest wires a node
# (e.g. an installed wheel used outside the repository, without ``Agents/``).
_DEFAULT_NODE_PROMPTS = {
    "researcher": RESEARCHER_PROMPT,
    "coder": CODER_PROMPT,
    "reviewer": REVIEWER_PROMPT,
}


def manifest_node_prompt(agents_root: str, manifest: AgentManifest) -> str:
    """System prompt for one manifest-wired swarm node.

    Preference order: the role contract (``Agents/{Name}/AGENTS.md``), then the
    manifest ``role`` line, then a one-line default naming the node.

    Args:
        agents_root: Directory holding the ``Agents/{Name}/`` folders.
        manifest: Validated manifest of the wired agent.

    Returns:
        The prompt text, truncated to the manifest's prompt budget.
    """
    contract = role_contract(agents_root, manifest.name)
    text = contract or manifest.role
    if not text:
        node = manifest.langgraph_node or manifest.name.lower()
        return f"You are the {node}. Be brief."
    budget = TokenBudget(max_tokens=manifest.token_budget.max_prompt)
    return budget.pack(system=text, memories=[], turns=[]).system
