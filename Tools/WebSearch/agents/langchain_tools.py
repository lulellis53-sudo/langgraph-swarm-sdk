"""One LangChain tool for WebSearch: ``web_search`` (packed brief).

Same contract as the MCP tool and ``websearch --prompt --max-tokens --min-score``.
"""

from __future__ import annotations

lazy from collections.abc import Mapping
lazy from typing import TYPE_CHECKING

lazy from WebSearch.agents.agent_tools import (
    DEFAULT_LIMIT,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MIN_SCORE,
    search_brief,
)
lazy from WebSearch.frontend.websearchers import ProvidersConfig, SearchFn

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool


def websearch_langchain_tools(
    *,
    config: ProvidersConfig | None = None,
    backends: Mapping[str, SearchFn] | None = None,
) -> list[BaseTool]:
    """Return the single ``web_search`` tool for ``create_agent`` / ``bind_tools``.

    Args:
        config: Provider registry; default ``load_providers()``.
        backends: Searcher id → callable; use in tests to avoid live HTTP.

    Returns:
        A one-element list containing ``web_search``.
    """
    from langchain_core.tools import StructuredTool

    def web_search(
        query: str,
        limit: int = DEFAULT_LIMIT,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        min_score: float = DEFAULT_MIN_SCORE,
    ) -> str:
        """Search the web and return a token-budgeted ``[n] title - url`` brief.

        ``max_tokens`` is max(tiktoken cl100k_base, Qwen3-Embedding int8 tokenizer).
        ``min_score`` (0..1, default 0.25) drops off-target hits.
        """
        return search_brief(
            query,
            limit=limit,
            max_tokens=max_tokens,
            min_score=min_score,
            config=config,
            backends=backends,
        )

    return [
        StructuredTool.from_function(
            func=web_search,
            name="web_search",
            description=(
                "Search the web across every configured provider in parallel, "
                "fuse and dedupe results, and return a short numbered brief with URLs, "
                "bounded by max_tokens (tiktoken + Qwen int8 tokenizer)."
            ),
        )
    ]


__all__ = ["websearch_langchain_tools"]
