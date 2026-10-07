5"""LangChain / LangGraph tool bindings for WebSearch agent helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from typing import TYPE_CHECKING

from WebSearch.agent_tools import dedupe_documents, search_brief, search_hits, summarize_documents
from WebSearch.backend.docs import ExtractedDoc
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
    """Return web search, document dedupe, and semantic summary tools.

    Args:
        config: Provider registry; default ``load_providers()``.
        backends: Searcher id → callable; use in tests to avoid live HTTP.

    Returns:
        Four tools: ``web_search_brief``, ``web_search_hits``, ``web_dedupe_documents``,
        and ``web_summarize_documents``.
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

    def web_dedupe_documents(
        documents: list[dict[str, object]],
    ) -> dict[str, object]:
        """Normalize extracted documents and remove exact, URL, and near duplicates."""
        docs = [
            ExtractedDoc(
                url=str(doc["url"]),
                text=str(doc["text"]),
                extractor=str(doc.get("extractor", "agent")),
                raw_chars=int(doc.get("raw_chars", 0)),
            )
            for doc in documents
        ]
        return dedupe_documents(docs)

    def web_summarize_documents(
        query: str, documents: list[dict[str, object]], max_results: int = 10
    ) -> dict[str, object]:
        """Use semantic vector search to rank extracted documents and summarize matches."""
        docs = [
            ExtractedDoc(
                url=str(doc["url"]),
                text=str(doc["text"]),
                extractor=str(doc.get("extractor", "agent")),
                raw_chars=int(doc.get("raw_chars", 0)),
            )
            for doc in documents
        ]
        return summarize_documents(query, docs, max_results=max_results)

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
            func=web_dedupe_documents,
            name="web_dedupe_documents",
            description="Normalize extracted web documents and return unique pages with counts.",
        ),
        StructuredTool.from_function(
            func=web_summarize_documents,
            name="web_summarize_documents",
            description=(
                "Rank extracted web documents with semantic vector search and return concise "
                "query-relevant summaries."
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
