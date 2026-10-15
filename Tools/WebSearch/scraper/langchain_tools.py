"""LangChain / LangGraph tool bindings for WebScraper search and semantic pack.

Optional extra: ``uv sync --project WebScraper --group dev`` (includes
``langchain-core``). Bind on an agent with
``create_agent(model, tools=webscraper_langchain_tools())``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from WebSearch.scraper.agent_tools import search_brief, search_hits, semantic_brief, semantic_hits

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

FetchFn = Callable[[str, int], list[dict[str, Any]]]
SemanticFn = Callable[[str, int, str | None], list[dict[str, Any]]]


def webscraper_langchain_tools(
    *,
    fetch: FetchFn | None = None,
    semantic: SemanticFn | None = None,
) -> list[BaseTool]:
    """Return compact-search and semantic-search tools for a LangChain agent.

    Args:
        fetch: ``(query, limit) -> raw hit dicts``. Default talks to SearXNG.
        semantic: ``(query, limit, url_contains) -> chunk dicts``. Default uses
            the local pgvector store.

    Returns:
        Four tools: ``webscraper_search_brief``, ``webscraper_search_hits``,
        ``webscraper_semantic_search``, ``webscraper_semantic_hits``.
    """
    from langchain_core.tools import StructuredTool

    def webscraper_search_brief(
        query: str,
        limit: int = 8,
        max_tokens: int = 400,
        min_score: float | None = None,
    ) -> str:
        """Search the web and return a token-budgeted ``[title](url)`` brief."""
        return search_brief(
            query, limit=limit, max_tokens=max_tokens, min_score=min_score, fetch=fetch
        )

    def webscraper_search_hits(
        query: str,
        limit: int = 8,
        max_tokens: int = 400,
        min_score: float | None = None,
    ) -> list[dict[str, Any]]:
        """Search the web and return packed structured hits."""
        return search_hits(
            query, limit=limit, max_tokens=max_tokens, min_score=min_score, fetch=fetch
        )

    def webscraper_semantic_search(
        query: str,
        limit: int = 5,
        max_tokens: int = 600,
        min_score: float | None = None,
        url_contains: str | None = None,
    ) -> str:
        """Search ingested pages and return a packed brief."""
        return semantic_brief(
            query,
            limit=limit,
            max_tokens=max_tokens,
            min_score=min_score,
            url_contains=url_contains,
            semantic=semantic,
        )

    def webscraper_semantic_hits(
        query: str,
        limit: int = 5,
        max_tokens: int = 600,
        min_score: float | None = None,
        url_contains: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search ingested pages and return packed structured chunks."""
        return semantic_hits(
            query,
            limit=limit,
            max_tokens=max_tokens,
            min_score=min_score,
            url_contains=url_contains,
            semantic=semantic,
        )

    return [
        StructuredTool.from_function(func=fn, name=name, description=desc)
        for fn, name, desc in (
            (
                webscraper_search_brief,
                "webscraper_search_brief",
                "Search the web via local SearXNG and return a short numbered brief.",
            ),
            (
                webscraper_search_hits,
                "webscraper_search_hits",
                "Search the web via SearXNG; packed hits (title, url, snippet, score, source).",
            ),
            (
                webscraper_semantic_search,
                "webscraper_semantic_search",
                "Semantic search over ingested pages, packed into max_tokens.",
            ),
            (
                webscraper_semantic_hits,
                "webscraper_semantic_hits",
                "Semantic search over ingested pages; packed title/url/snippet/score/source.",
            ),
        )
    ]
