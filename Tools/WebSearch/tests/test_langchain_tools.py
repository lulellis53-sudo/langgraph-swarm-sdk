"""Offline tests for the single LangChain ``web_search`` tool."""

from __future__ import annotations

from typing import TYPE_CHECKING

from WebSearch.agents.langchain_tools import websearch_langchain_tools
from WebSearch.frontend.websearchers import ProvidersConfig, SearcherSpec, SearchFn, SearchHit

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool


def _config(*searcher_ids: str) -> ProvidersConfig:
    """Minimal config with only the given searcher ids."""
    return ProvidersConfig(
        version=1,
        searchers=tuple(
            SearcherSpec(id=sid, kind="websearcher", enabled=True) for sid in searcher_ids
        ),
    )


def _hit(title: str, url: str, snippet: str, searcher: str = "fake") -> SearchHit:
    """Build a search hit."""
    return SearchHit(title=title, url=url, snippet=snippet, searcher_id=searcher)


def _backends() -> dict[str, SearchFn]:
    """Fake backend returning one strong and one off-target hit."""

    def backend(query: str, spec: SearcherSpec) -> list[SearchHit]:
        return [
            _hit(
                "LangGraph orchestration",
                "https://langchain.github.io/langgraph/",
                "Low-level orchestration for multi-agent workflows.",
                spec.id,
            ),
            _hit(
                "Banana bread recipes",
                "https://recipes.example/banana-bread",
                "Moist banana bread with walnuts.",
                spec.id,
            ),
        ]

    return {"fake": backend}


def _tools() -> list[BaseTool]:
    return websearch_langchain_tools(config=_config("fake"), backends=_backends())


def test_one_tool_named_web_search() -> None:
    names = {tool.name for tool in _tools()}
    assert names == {"web_search"}


def test_schema_exposes_agentic_cli_args() -> None:
    tool = _tools()[0]
    assert "max_tokens" in tool.args
    assert "min_score" in tool.args
    assert "limit" in tool.args


def test_brief_respects_token_budget() -> None:
    from WebSearch.agents.agent_tools import count_tokens

    result = _tools()[0].invoke({"query": "langgraph orchestration", "max_tokens": 120})
    assert isinstance(result, str)
    assert "Sources:" in result
    assert count_tokens(result) <= 160


def test_default_min_score_filters_off_target() -> None:
    result = _tools()[0].invoke({"query": "langgraph orchestration"})
    assert "LangGraph" in result
    assert "Banana bread" not in result


def test_agent_hit_schema() -> None:
    hit = _hit("T", "https://ex.test/a", "snippet")
    assert hit.as_agent_dict() == {
        "title": "T",
        "url": "https://ex.test/a",
        "snippet": "snippet",
        "score": 0.0,
        "source": "fake",
    }
