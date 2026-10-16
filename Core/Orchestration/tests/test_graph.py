"""Offline tests for the planner -> researcher -> writer graph."""

from __future__ import annotations

import pytest
from langchain_core.language_models.fake_chat_models import (
    FakeListChatModel,
    GenericFakeChatModel,
)
from langchain_core.messages import AIMessage

from orchestration.graph import build_graph


def test_graph_runs_planner_researcher_writer_in_order() -> None:
    seen_plans: list[str] = []

    def search(plan: str) -> str:
        seen_plans.append(plan)
        return "notes"

    llm = FakeListChatModel(responses=["step 1; step 2", "final answer"])
    result = build_graph(llm, search).invoke({"goal": "compare two options"})

    assert result["plan"] == "step 1; step 2"
    assert seen_plans == ["step 1; step 2"]
    assert result["research"] == "notes"
    assert result["answer"] == "final answer"


def test_search_failure_propagates() -> None:
    def search(plan: str) -> str:
        raise RuntimeError("search backend down")

    llm = FakeListChatModel(responses=["plan"])
    with pytest.raises(RuntimeError, match="search backend down"):
        build_graph(llm, search).invoke({"goal": "anything"})


def test_empty_goal_still_produces_each_stage() -> None:
    llm = FakeListChatModel(responses=["plan", "answer"])
    result = build_graph(llm, lambda plan: "notes").invoke({"goal": ""})

    assert result["answer"] == "answer"


def test_list_content_is_joined_to_text() -> None:
    block_reply = AIMessage(
        content=[{"type": "text", "text": "block "}, {"type": "text", "text": "answer"}]
    )
    llm = GenericFakeChatModel(messages=iter([AIMessage(content="plan"), block_reply]))

    result = build_graph(llm, lambda plan: "notes").invoke({"goal": "x"})

    assert result["answer"] == "block answer"
