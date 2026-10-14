"""Unit tests for the Core/Sdk module.

Validates the public API, SwarmState structure, multi-agent handoffs,
middleware pipeline, and LangGraph Swarm compilation.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

import sdk
from sdk import (
    Swarm,
    SwarmAgent,
    SwarmState,
    build_default_middleware,
    create_handoff,
)


def test_sdk_public_exports() -> None:
    """Verify that all symbols declared in __all__ are importable and present."""
    for symbol in sdk.__all__:
        assert hasattr(sdk, symbol), f"Missing symbol: {symbol}"


def test_swarm_state_structure() -> None:
    """Verify SwarmState dictionary fields and typing."""
    state: SwarmState = {
        "messages": [HumanMessage(content="Hello from test")],
        "active_agent": "Alice",
        "context": {"session_id": "test-123"},
        "handoff_history": [{"from": "Alice", "to": "Bob"}],
    }
    assert state["active_agent"] == "Alice"
    assert len(state["messages"]) == 1
    assert state["context"]["session_id"] == "test-123"


def test_create_handoff_metadata() -> None:
    """Ensure handoff tools are created with proper naming and metadata."""
    handoff_tool = create_handoff("Bob", "Transfer to Bob for calculations.")
    assert handoff_tool.name == "transfer_to_Bob"
    assert "Bob" in handoff_tool.description


def test_middleware_construction() -> None:
    """Validate middleware pipeline generation with context editing."""
    pipeline = build_default_middleware(
        context_editing=True,
        summarization=False,
        trigger_tokens=2000,
        keep_tool_uses=2,
    )
    assert isinstance(pipeline, list)
    assert len(pipeline) >= 1


def test_swarm_agent_and_workflow_compile() -> None:
    """Test swarm compilation with two specialist agents."""
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

    fake_model = FakeMessagesListChatModel(responses=[HumanMessage(content="Mock response")])

    alice = SwarmAgent(
        name="Alice",
        system_prompt="You are Alice, specialized in math.",
        model=fake_model,
        enable_middleware=False,
    )
    bob = SwarmAgent(
        name="Bob",
        system_prompt="You are Bob, specialized in research.",
        model=fake_model,
        enable_middleware=False,
    )

    checkpointer = InMemorySaver()
    swarm = Swarm(
        agents=[alice, bob],
        default_active_agent="Alice",
        checkpointer=checkpointer,
    )

    app = swarm.compile()
    assert app is not None
    assert hasattr(app, "invoke")
    assert hasattr(app, "stream")
    assert hasattr(app, "ainvoke")
    assert hasattr(app, "astream")

    # Verify history empty initially
    history = swarm.get_history(thread_id="test-thread-1")
    assert history == []

