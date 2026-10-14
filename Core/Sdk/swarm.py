"""LangGraph Swarm Orchestrator.

High-level multi-agent swarm engine utilizing official LangGraph-Swarm APIs,
handoff tools, state persistence, and LangSmith tracing integration.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from typing import Any

from Core.Sdk.middleware import build_default_middleware
from Core.Sdk.models import load_chat_model
from Core.Sdk.state import SwarmState
from Core.Sdk.tracing import SwarmTracerCallbackHandler, is_langsmith_enabled
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

logger = logging.getLogger(__name__)


def create_handoff(
    agent_name: str,
    description: str | None = None,
) -> Any:
    """Create a LangGraph Swarm handoff tool.

    Args:
        agent_name: Destination agent identifier.
        description: Description instructing the LLM when to trigger the handoff.

    Returns:
        Configured handoff tool with `__handoff_destination` metadata.
    """
    from langgraph_swarm import create_handoff_tool

    desc = description or f"Transfer conversation to {agent_name}."
    return create_handoff_tool(
        agent_name=agent_name,
        name=f"transfer_to_{agent_name}",
        description=desc,
    )


class SwarmAgent:
    """Defines a specialist agent persona within the swarm."""

    def __init__(
        self,
        name: str,
        system_prompt: str,
        *,
        model: BaseChatModel | str = "gpt-4o",
        tools: Sequence[Callable[..., Any] | Any] | None = None,
        enable_middleware: bool = True,
    ) -> None:
        self.name = name
        self.system_prompt = system_prompt
        self.model = load_chat_model(model) if isinstance(model, str) else model
        self.tools = list(tools) if tools is not None else []
        self.enable_middleware = enable_middleware

    def compile(self, peer_names: Sequence[str]) -> Any:
        """Compile this specialist into a LangChain agent graph with peer handoff tools."""
        from langchain.agents import create_agent

        # Automatically assemble handoff tools to all peer agents
        handoff_tools = [
            create_handoff(peer, f"Transfer conversation to {peer}.")
            for peer in peer_names
            if peer != self.name
        ]
        all_tools = self.tools + handoff_tools

        middleware = build_default_middleware() if self.enable_middleware else []

        return create_agent(
            model=self.model,
            tools=all_tools,
            system_prompt=self.system_prompt,
            middleware=middleware,
            name=self.name,
        )


class Swarm:
    """Enterprise LangGraph Swarm Orchestrator.

    Coordinates specialist agents, handles dynamic handoffs, persists conversation
    state via checkpointers, and streams events to LangSmith.
    """

    def __init__(
        self,
        agents: Sequence[SwarmAgent],
        *,
        default_active_agent: str | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
    ) -> None:
        if not agents:
            raise ValueError("Swarm must be initialized with at least one SwarmAgent.")

        self.agents = {agent.name: agent for agent in agents}
        self.default_active_agent = default_active_agent or sorted(self.agents.keys())[0]
        self.checkpointer = checkpointer or InMemorySaver()
        self._compiled_app: Any = None

    def compile(self) -> Any:
        """Compile the multi-agent swarm into a runnable LangGraph application."""
        from langgraph_swarm import create_swarm

        peer_names = list(self.agents.keys())
        compiled_agents = [
            agent.compile(peer_names=peer_names)
            for agent in self.agents.values()
        ]

        workflow = create_swarm(
            compiled_agents,
            default_active_agent=self.default_active_agent,
            state_schema=SwarmState,
        )

        self._compiled_app = workflow.compile(checkpointer=self.checkpointer)
        return self._compiled_app

    @classmethod
    def from_manifests(
        cls,
        agent_names: Sequence[str] | None = None,
        *,
        agents_dir: str | Path | None = None,
        default_active_agent: str | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
        model_override: str | None = None,
        enable_middleware: bool = True,
    ) -> Swarm:
        """Construct a Swarm using the canonical personas from Swarm/Agents/.

        Args:
            agent_names: List of agent persona directory names under Agents/
                (e.g. ['Orchestrator', 'Coder', 'Reviewer']). If None, defaults
                to the core coordination agents from coordination.yaml.
            agents_dir: Path to the Agents/ tree. Auto-resolved if None.
            default_active_agent: Initial active agent. Defaults to Orchestrator or first agent.
            checkpointer: Checkpointer persistence engine. Defaults to InMemorySaver.
            model_override: Optional model name to override manifests (e.g. for testing/mocking).
            enable_middleware: Attach context-editing middleware.

        Returns:
            Configured Swarm instance ready for compilation and turn execution.
        """
        from pathlib import Path
        from swarm_sdk.agents.manifest import (
            agents_root,
            load_all_agent_manifests,
            role_contract,
        )

        root_path = Path(agents_dir) if agents_dir else agents_root()
        all_manifests = load_all_agent_manifests(root_path)

        if not agent_names:
            agent_names = [
                "Orchestrator",
                "Coder",
                "Reviewer",
                "Tester",
                "Debugger",
                "Documenter",
                "Architect",
                "Planner",
            ]

        swarm_agents: list[SwarmAgent] = []
        for name in agent_names:
            if name not in all_manifests:
                logger.warning("Agent '%s' not found under %s; skipping", name, root_path)
                continue

            manifest = all_manifests[name]
            prompt = role_contract(str(root_path), name)
            if not prompt:
                prompt = f"You are the {name} agent. Role: {manifest.role}."

            selected_model = model_override or manifest.model or "gpt-4o"
            swarm_agents.append(
                SwarmAgent(
                    name=name,
                    system_prompt=prompt,
                    model=selected_model,
                    enable_middleware=enable_middleware,
                )
            )

        if not swarm_agents:
            raise ValueError(f"No valid agents could be loaded from {root_path} for {agent_names}")

        default_agent = default_active_agent or ("Orchestrator" if "Orchestrator" in [a.name for a in swarm_agents] else swarm_agents[0].name)
        return cls(
            agents=swarm_agents,
            default_active_agent=default_agent,
            checkpointer=checkpointer,
        )


    @property
    def app(self) -> Any:
        """Return the compiled swarm app, compiling automatically if needed."""
        if self._compiled_app is None:
            self.compile()
        return self._compiled_app

    def run(
        self,
        user_message: str,
        *,
        thread_id: str = "default",
        callbacks: list[Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a turn across the swarm.

        Args:
            user_message: Human message input string.
            thread_id: Session identifier to maintain multi-turn memory.
            callbacks: Optional additional callback handlers.

        Returns:
            Final state dictionary including messages and active_agent.
        """
        config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}

        active_callbacks = list(callbacks or [])
        if is_langsmith_enabled():
            active_callbacks.append(SwarmTracerCallbackHandler())

        if active_callbacks:
            config["callbacks"] = active_callbacks

        payload = {"messages": [HumanMessage(content=user_message)]}
        return self.app.invoke(payload, config)

    async def arun(
        self,
        user_message: str,
        *,
        thread_id: str = "default",
        callbacks: list[Any] | None = None,
    ) -> dict[str, Any]:
        """Asynchronously execute a turn across the swarm."""
        config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}

        active_callbacks = list(callbacks or [])
        if is_langsmith_enabled():
            active_callbacks.append(SwarmTracerCallbackHandler())

        if active_callbacks:
            config["callbacks"] = active_callbacks

        payload = {"messages": [HumanMessage(content=user_message)]}
        return await self.app.ainvoke(payload, config)

    def stream(
        self,
        user_message: str,
        *,
        thread_id: str = "default",
        stream_mode: str = "updates",
        callbacks: list[Any] | None = None,
    ) -> Iterator[Any]:
        """Stream swarm execution events."""
        config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}

        active_callbacks = list(callbacks or [])
        if is_langsmith_enabled():
            active_callbacks.append(SwarmTracerCallbackHandler())

        if active_callbacks:
            config["callbacks"] = active_callbacks

        payload = {"messages": [HumanMessage(content=user_message)]}
        yield from self.app.stream(payload, config, stream_mode=stream_mode)

    async def astream(
        self,
        user_message: str,
        *,
        thread_id: str = "default",
        stream_mode: str = "updates",
        callbacks: list[Any] | None = None,
    ) -> AsyncIterator[Any]:
        """Asynchronously stream swarm execution events."""
        config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}

        active_callbacks = list(callbacks or [])
        if is_langsmith_enabled():
            active_callbacks.append(SwarmTracerCallbackHandler())

        if active_callbacks:
            config["callbacks"] = active_callbacks

        payload = {"messages": [HumanMessage(content=user_message)]}
        async for chunk in self.app.astream(payload, config, stream_mode=stream_mode):
            yield chunk

    def get_history(self, *, thread_id: str = "default") -> list[BaseMessage]:
        """Inspect message history for a conversation thread."""
        config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
        state_snapshot = self.app.get_state(config)
        if state_snapshot and state_snapshot.values:
            return state_snapshot.values.get("messages", [])
        return []


__all__ = [
    "create_handoff",
    "SwarmAgent",
    "Swarm",
]
