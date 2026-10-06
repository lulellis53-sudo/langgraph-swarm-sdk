"""PydanticAI nodes inside ``langgraph_swarm.create_swarm`` (text answers and typed handoffs)."""

from __future__ import annotations

import pytest

pytest.importorskip("pydantic_ai")

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph_swarm import create_swarm
from pydantic import ValidationError
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from swarm_sdk.core.pydantic_node import (
    Handoff,
    handoff_type,
    pydantic_ai_node,
    to_model_history,
)


def _text_model(reply: str) -> FunctionModel:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages, info
        return ModelResponse(parts=[TextPart(content=reply)])

    return FunctionModel(respond)


def _handoff_model(agent: str, reason: str) -> FunctionModel:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages
        tool = info.output_tools[0]  # one non-str output type: the Handoff tool
        return ModelResponse(parts=[ToolCallPart(tool.name, {"agent": agent, "reason": reason})])

    return FunctionModel(respond)


def _swarm(coder_model: FunctionModel, tester_model: FunctionModel):
    coder = pydantic_ai_node("coder", coder_model, "You code.", peers=["tester"])
    tester = pydantic_ai_node("tester", tester_model, "You test.", peers=["coder"])
    return create_swarm([coder, tester], default_active_agent="coder").compile(
        checkpointer=InMemorySaver()
    )


def test_handoff_type_restricts_agent_to_peers() -> None:
    kind = handoff_type(["tester"])
    assert issubclass(kind, Handoff)
    assert kind(agent="tester").agent == "tester"
    with pytest.raises(ValidationError):
        kind(agent="stranger")


def test_handoff_type_rejects_empty_peers() -> None:
    with pytest.raises(ValueError, match="at least one peer"):
        handoff_type([])


def test_history_keeps_text_and_uses_trailing_human_as_prompt() -> None:
    history, prompt = to_model_history(
        [HumanMessage("hi"), AIMessage("hello"), AIMessage(""), HumanMessage("now?")]
    )
    assert prompt == "now?"
    assert len(history) == 2


def test_history_without_trailing_human_continues() -> None:
    _, prompt = to_model_history([HumanMessage("hi"), AIMessage("Transferred to tester")])
    assert prompt == "Continue helping the user."


async def test_text_answer_keeps_active_agent() -> None:
    app = _swarm(_text_model("done"), _text_model("unused"))
    state = await app.ainvoke(
        {"messages": [{"role": "user", "content": "build it"}], "active_agent": "coder"},
        {"configurable": {"thread_id": "t1"}},
    )
    assert state["active_agent"] == "coder"
    assert state["messages"][-1].content == "done"


async def test_handoff_switches_agent_and_peer_answers() -> None:
    app = _swarm(_handoff_model("tester", "needs tests"), _text_model("tested"))
    state = await app.ainvoke(
        {"messages": [{"role": "user", "content": "build and test it"}], "active_agent": "coder"},
        {"configurable": {"thread_id": "t2"}},
    )
    assert state["active_agent"] == "tester"
    assert state["messages"][-1].content == "tested"
    assert any("Transferred to tester: needs tests" == m.content for m in state["messages"])
