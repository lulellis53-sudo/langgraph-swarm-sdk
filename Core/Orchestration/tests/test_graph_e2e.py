"""End-to-end offline invoke: compile graph and assert full state."""

from __future__ import annotations

from langchain_core.language_models.fake_chat_models import FakeListChatModel

from orchestration.graph import build_graph


def test_graph_e2e_invoke_populates_all_state_keys() -> None:
    llm = FakeListChatModel(responses=["step a; step b", "written answer"])
    graph = build_graph(llm, lambda plan: f"notes for: {plan}")
    result = graph.invoke({"goal": "summarize options"})

    assert result["goal"] == "summarize options"
    assert result["plan"] == "step a; step b"
    assert result["research"] == "notes for: step a; step b"
    assert result["answer"] == "written answer"
