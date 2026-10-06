"""LangChain / LangGraph tool bindings for WebSearch agent helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from typing import TYPE_CHECKING

from WebSearch.agent_tools import search_brief, search_hits
from WebSearch.frontend.websearchers import ProvidersConfig, SearchFn, SearchHit

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool


def _hits_payload(hits: list[SearchHit]) -> list[dict[str, object]]:
    return [asdict(hit) for hit in hits]


def websearch_langchain_tools(
    *,
    config: ProvidersConfig | None = None,
    backends: Mapping[str, SearchFn] | None = None,
) -> list[BaseTool]:
    """Return LangChain tools that call :func:`search_brief` and :func:`search_hits`.

    Args:
        config: Provider registry; default ``load_providers()``.
        backends: Searcher id → callable; use in tests to avoid live HTTP.

    Returns:
        Two tools: ``web_search_brief`` (prompt-ready text) and ``web_search_hits``
        (structured hit dicts).
    """
    from langchain_core.tools import StructuredTool

    def web_search_brief(query: str, limit: int = 5, max_chars: int = 1200) -> str:
        """Run parallel multi-provider web search and return a numbered prompt brief."""
        return search_brief(
            query,
            limit=limit,
            max_chars=max_chars,
            config=config,
            backends=backends,
        )

    def web_search_hits(query: str, limit: int = 5) -> list[dict[str, object]]:
        """Run parallel multi-provider web search and return structured hits."""
        hits = search_hits(
            query,
            limit=limit,
            config=config,
            backends=backends,
        )
        return _hits_payload(hits)

    return [
        StructuredTool.from_function(
            func=web_search_brief,
            name="web_search_brief",
            description=(
                "Search the web across every configured provider in parallel, "
                "fuse and dedupe results, and return a short numbered brief with URLs."
            ),
        ),
        StructuredTool.from_function(
            func=web_search_hits,
            name="web_search_hits",
            description=(
                "Search the web across every configured provider in parallel and "
                "return structured hits (title, url, snippet, searcher_id)."
            ),
        ),
    ]


__all__ = ["websearch_langchain_tools"]
