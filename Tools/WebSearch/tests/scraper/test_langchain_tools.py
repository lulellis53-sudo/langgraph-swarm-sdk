"""Offline tests for WebScraper LangChain tool bindings."""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("langchain_core")


def _fetch(_query: str, _limit: int) -> list[dict[str, Any]]:
    return [
        {
            "title": "LangGraph orchestration",
            "url": "https://langchain.github.io/langgraph/",
            "content": "Low-level orchestration for multi-agent workflows.",
        },
        {
            "title": "Banana bread recipes",
            "url": "https://recipes.example/banana-bread",
            "content": "Moist banana bread with walnuts.",
        },
    ]


def _semantic(_query: str, _limit: int, _url: str | None) -> list[dict[str, Any]]:
    return [
        {
            "title": "chunk",
            "url": "https://docs.example/a",
            "snippet": "LangGraph orchestration for agents.",
            "score": 0.9,
            "chunk_idx": 0,
            "source": "pgvector",
        }
    ]


def _tools():
    from WebSearch.scraper.langchain_tools import webscraper_langchain_tools

    return webscraper_langchain_tools(fetch=_fetch, semantic=_semantic)


def test_tool_names() -> None:
    names = {tool.name for tool in _tools()}
    assert names == {
        "webscraper_search_brief",
        "webscraper_search_hits",
        "webscraper_semantic_search",
        "webscraper_semantic_hits",
    }


def test_brief_schema_exposes_token_budget_params() -> None:
    brief = next(tool for tool in _tools() if tool.name == "webscraper_search_brief")
    assert "max_tokens" in brief.args
    assert "min_score" in brief.args


def test_brief_min_score_filters_off_target() -> None:
    brief = next(tool for tool in _tools() if tool.name == "webscraper_search_brief")
    result = brief.invoke({"query": "langgraph orchestration", "min_score": 0.3})
    assert "LangGraph" in result
    assert "banana" not in result.lower()


def test_hits_are_structured() -> None:
    hits_tool = next(tool for tool in _tools() if tool.name == "webscraper_search_hits")
    rows = hits_tool.invoke({"query": "langgraph orchestration", "min_score": 0.3})
    assert rows[0]["url"] == "https://langchain.github.io/langgraph"
    assert set(rows[0]) == {"title", "url", "snippet", "score", "source"}


def test_semantic_tools() -> None:
    tools = {tool.name: tool for tool in _tools()}
    brief = tools["webscraper_semantic_search"].invoke({"query": "langgraph"})
    assert "LangGraph" in brief
    rows = tools["webscraper_semantic_hits"].invoke({"query": "langgraph"})
    assert rows[0]["url"] == "https://docs.example/a"
