"""Handoff-swarm graph assembly: agents, tools, middleware, and compilation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from swarm_sdk.agents.manifest import AgentManifest, agents_root
from swarm_sdk.models.chat import load_chat_model

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver

    from swarm_sdk.core.swarm import CompiledGraph, SwarmSDK
from swarm_sdk.core.prompts import (
    _DEFAULT_NODE_PROMPTS,
    manifest_node_prompt,
)

logger = logging.getLogger(__name__)


def _handoff(agent_name: str, description: str):
    """Keyword-only langgraph-swarm API: agent_name, optional name and description."""
    from langgraph_swarm import create_handoff_tool

    return create_handoff_tool(
        agent_name=agent_name,
        name=f"transfer_to_{agent_name}",
        description=description,
    )


class GraphBuilder:
    """Compiles the handoff swarm graph from the Agents/ manifest catalog."""

    def __init__(self, sdk: SwarmSDK) -> None:
        self._sdk = sdk

    def model_for_node(self, node: str):
        """Return the model for a handoff node: injected model, manifest model, or default."""
        sdk = self._sdk
        if sdk._specialist_model is not None:
            return sdk._specialist_model
        if sdk.settings.model:
            return load_chat_model(sdk.settings.model)
        manifest = sdk._langgraph_manifests.get(node)
        if manifest is None:
            return sdk._specialist()
        if manifest.model:
            return load_chat_model(manifest.model)
        route = sdk._selector.select(manifest.think_level)
        return load_chat_model(route.name)

    @property
    def default_agent(self) -> str:
        """Entry node for new threads; ``researcher`` whenever it is wired."""
        sdk = self._sdk
        nodes = set(sdk._langgraph_manifests) or set(_DEFAULT_NODE_PROMPTS)
        return "researcher" if "researcher" in nodes else sorted(nodes)[0]

    def jev_default_agent(self, text: str) -> str:
        """Pick the entry agent using JEV's deterministic choice router.

        Falls back to the static default when JEV routing is disabled, the router
        raises, or the selected choice is not a wired node. This keeps new-thread
        startup deterministic and sub-35ms when ``jev_routing`` is enabled.

        Args:
            text: The original user message.

        Returns:
            Name of the entry agent to activate.
        """
        sdk = self._sdk
        if not sdk.settings.jev_routing:
            return self.default_agent
        candidates = sorted(sdk._langgraph_manifests) or sorted(_DEFAULT_NODE_PROMPTS)
        try:
            decision = sdk._jev.evaluate_choice(text, candidates)
        except Exception as exc:
            logger.debug("JEV entry-agent routing failed (%s); falling back", exc)
            return self.default_agent
        if decision.selected_choice in candidates:
            return decision.selected_choice
        return self.default_agent

    def node_tools(self, manifest: AgentManifest | None, peers: list[str]) -> list[object]:
        """Tools for one swarm node: capability-gated extras plus handoffs.

        A manifest advertising the ``web_search`` capability also gets the
        WebSearch LangChain tools when ``Settings.enable_websearch_tools`` is
        set and the package is importable; otherwise only handoff tools.
        """
        from swarm_sdk.core import (
            swarm as swarm_module,  # noqa: PLC0415 — late binding avoids circularity
        )

        sdk = self._sdk
        handoffs = [_handoff(peer, f"Hand off {peer} work.") for peer in peers]
        if (
            manifest is not None
            and sdk.settings.enable_websearch_tools
            and "web_search" in manifest.capabilities
        ):
            # Late-bound: tests patch ``swarm_sdk.core.swarm._websearch_tools`` by dotted path.
            return [*swarm_module._websearch_tools(), *handoffs]
        return handoffs

    def node_middleware(self) -> list[object]:
        """Token-saving middleware for every swarm agent node.

        Context editing (`ClearToolUsesEdit`) replaces old tool uses — handoff
        results, tool outputs — with a placeholder once the replayed transcript
        passes ``swarm_edit_trigger_tokens`` approximate tokens. It makes no
        model calls. Summarization (opt-in via ``swarm_summarization``) instead
        rewrites the old transcript into a model-generated summary, spending
        one extra model call per trigger.

        The transcript is replayed on every turn through the checkpointer, so
        clearing stale tool outputs cuts the prompt tokens of *all subsequent
        turns*, which is the main token lever of the handoff swarm.
        """
        from langchain.agents.middleware import ContextEditingMiddleware, SummarizationMiddleware
        from langchain.agents.middleware.context_editing import ClearToolUsesEdit

        sdk = self._sdk
        if not sdk.settings.swarm_context_editing and not sdk.settings.swarm_summarization:
            return []
        middleware: list[object] = []
        if sdk.settings.swarm_context_editing:
            middleware.append(
                ContextEditingMiddleware(
                    edits=[
                        ClearToolUsesEdit(
                            trigger=sdk.settings.swarm_edit_trigger_tokens,
                            keep=sdk.settings.swarm_edit_keep_tool_uses,
                        )
                    ]
                )
            )
        if sdk.settings.swarm_summarization:
            middleware.append(
                SummarizationMiddleware(
                    model=sdk._specialist(),
                    trigger=("tokens", sdk.settings.swarm_edit_trigger_tokens * 2),
                    keep=("messages", 6),
                )
            )
        return middleware

    def build_graph(self, checkpointer: BaseCheckpointSaver | None) -> CompiledGraph:
        """Compile the handoff swarm from the Agents/ manifest catalog."""
        from langchain.agents import create_agent
        from langgraph_swarm import create_swarm

        # Runtime name for the cast below; a module-level import would be circular
        # (swarm.py imports this module), and by call time swarm is fully loaded.
        from swarm_sdk.core.swarm import CompiledGraph

        sdk = self._sdk
        # Nodes come from the Agents/ catalog: every manifest that wires a
        # ``langgraph_node`` becomes a specialist; prompts are that persona's
        # role contract. Without a catalog the default trio stands in.
        nodes = sorted(sdk._langgraph_manifests) or sorted(_DEFAULT_NODE_PROMPTS)
        root = str(agents_root())
        middleware = self.node_middleware()
        agents = []
        for node in nodes:
            manifest = sdk._langgraph_manifests.get(node)
            prompt = (
                manifest_node_prompt(root, manifest)
                if manifest is not None
                else _DEFAULT_NODE_PROMPTS.get(node, f"You are the {node}. Be brief.")
            )
            peers = [peer for peer in nodes if peer != node]
            agents.append(
                # Mixed handoff/websearch tool objects; the static overloads
                # only track the literal tool-list shape (cf. load_chat_model).
                create_agent(  # ty: ignore[no-matching-overload]
                    self.model_for_node(node),
                    tools=self.node_tools(manifest, peers),
                    system_prompt=prompt,
                    middleware=middleware,
                    name=node,
                )
            )
        workflow = create_swarm(agents, default_active_agent=self.default_agent)
        # Short-term: checkpointer (active_agent + messages per thread_id).
        # Long-term recall is SwarmSDK.memory (sqlite-vec / mem0 / …), not this store.
        return cast(CompiledGraph, workflow.compile(checkpointer=checkpointer))


__all__ = ["GraphBuilder"]
