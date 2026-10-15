"""Planner, researcher and writer agents wired as a LangGraph StateGraph.

The model and the search function are injected, so the graph runs offline in
tests and against any LangChain chat model in production. Tracing goes to
LangSmith when ``LANGSMITH_TRACING=true`` and ``LANGSMITH_API_KEY`` are set in
the environment; no key is read or stored by this module.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypedDict

lazy from langchain_core.language_models.chat_models import BaseChatModel
lazy from langchain_core.messages import HumanMessage
lazy from langgraph.graph import END, START, StateGraph

__all__ = ["OrchestrationState", "SearchFn", "build_graph"]

type SearchFn = Callable[[str], str]


class OrchestrationState(TypedDict):
    """Shared state passed between the planner, researcher and writer."""

    goal: str
    plan: str
    research: str
    answer: str


def _as_text(content: object) -> str:
    """Join LangChain message content into one string.

    Args:
        content: A string, or a list of content blocks (dicts with a ``text`` field).

    Returns:
        The text of the message.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block) for block in content
        )
    return str(content)


def build_graph(llm: BaseChatModel, search: SearchFn):
    """Compile the planner -> researcher -> writer graph.

    Args:
        llm: Chat model used by the planner and the writer.
        search: Callable that takes the plan text and returns research notes.

    Returns:
        A compiled LangGraph graph. Invoke it with ``{"goal": ...}``.
    """

    def planner(state: OrchestrationState) -> dict[str, str]:
        reply = llm.invoke([HumanMessage(content=f"Plan the steps to answer: {state['goal']}")])
        return {"plan": _as_text(reply.content)}

    def researcher(state: OrchestrationState) -> dict[str, str]:
        return {"research": search(state["plan"])}

    def writer(state: OrchestrationState) -> dict[str, str]:
        prompt = (
            f"Goal: {state['goal']}\n"
            f"Plan: {state['plan']}\n"
            f"Research: {state['research']}\n"
            "Write the final answer."
        )
        reply = llm.invoke([HumanMessage(content=prompt)])
        return {"answer": _as_text(reply.content)}

    graph = StateGraph(OrchestrationState)
    graph.add_node("planner", planner)
    graph.add_node("researcher", researcher)
    graph.add_node("writer", writer)
    graph.add_edge(START, "planner")
    graph.add_edge("planner", "researcher")
    graph.add_edge("researcher", "writer")
    graph.add_edge("writer", END)
    return graph.compile()
