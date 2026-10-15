"""Agent-facing search helpers: compact hits, token-budgeted briefs, semantic pack.

MCP tools and LangChain bindings both call this module. Pass ``fetch`` or
``semantic`` in tests so nothing hits the network or Postgres.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from WebSearch.scraper.hits import (
    as_agent_dict,
    compact_hits,
    format_brief,
    from_searxng,
    from_semantic_chunk,
)
from WebSearch.scraper.tokensaver import PackResult

__all__ = [
    "fetch_searx",
    "search_brief",
    "search_hits",
    "semantic_brief",
    "semantic_hits",
]

FetchFn = Callable[[str, int], list[dict[str, Any]]]
SemanticFn = Callable[[str, int, str | None], list[dict[str, Any]]]


def fetch_searx(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Top SearXNG results as ``title`` / ``url`` / ``snippet`` / ``source`` dicts."""
    import httpx2

    base = os.environ.get("SEARXNG_URL", "http://127.0.0.1:8888")
    with httpx2.Client() as client:
        resp = client.get(f"{base}/search", params={"format": "json", "q": query}, timeout=10.0)
        resp.raise_for_status()
        return from_searxng(resp.json().get("results", [])[:limit])


def _pack_search(
    query: str,
    *,
    limit: int,
    max_tokens: int,
    min_score: float | None,
    fetch: FetchFn | None,
) -> tuple[PackResult, int]:
    getter = fetch or fetch_searx
    raw = getter(query, max(limit * 2, 10))
    packed = compact_hits(
        raw, query, budget_tokens=max_tokens, min_score=min_score, limit=limit
    )
    return packed, len(raw)


def search_hits(
    query: str,
    *,
    limit: int = 8,
    max_tokens: int = 400,
    min_score: float | None = None,
    fetch: FetchFn | None = None,
) -> list[dict[str, Any]]:
    """Packed, scored hits ready for a tool-calling agent."""
    packed, _ = _pack_search(
        query, limit=limit, max_tokens=max_tokens, min_score=min_score, fetch=fetch
    )
    return [as_agent_dict(hit) for hit in packed.kept]


def search_brief(
    query: str,
    *,
    limit: int = 8,
    max_tokens: int = 400,
    min_score: float | None = None,
    fetch: FetchFn | None = None,
) -> str:
    """Numbered ``[title](url)`` brief bounded by ``max_tokens``."""
    packed, original = _pack_search(
        query, limit=limit, max_tokens=max_tokens, min_score=min_score, fetch=fetch
    )
    return format_brief(packed, original)


def _default_semantic(query: str, limit: int, url_contains: str | None) -> list[dict[str, Any]]:
    from WebSearch.scraper import semantic

    model = os.environ.get("WEBSCRAPER_EMBED_MODEL") or semantic.DEFAULT_MODEL
    store = semantic.PgVectorStore()
    (vector,) = semantic.embed_texts([query], model)
    hits = store.search(vector, model, limit, url_contains)
    if hits.is_empty():
        return []
    top = semantic.rerank(hits, query, min_similarity=0.12).head(limit)
    return [
        from_semantic_chunk(url, idx, text, score)
        for url, idx, text, score in top.select("url", "chunk_idx", "text", "score").iter_rows()
    ]


def pack_semantic(
    query: str,
    rows: list[dict[str, Any]],
    *,
    limit: int,
    max_tokens: int,
    min_score: float | None,
) -> PackResult:
    """Pack semantic chunks the same way as live search hits."""
    return compact_hits(
        rows,
        query,
        budget_tokens=max_tokens,
        min_score=min_score,
        limit=limit,
        snippet_chars=480,
    )


def _pack_semantic(
    query: str,
    *,
    limit: int,
    max_tokens: int,
    min_score: float | None,
    url_contains: str | None,
    semantic: SemanticFn | None,
) -> tuple[PackResult, int]:
    getter = semantic or _default_semantic
    rows = getter(query, max(limit * 3, 8), url_contains)
    packed = pack_semantic(
        query, rows, limit=limit, max_tokens=max_tokens, min_score=min_score
    )
    return packed, len(rows)


def semantic_hits(
    query: str,
    *,
    limit: int = 5,
    max_tokens: int = 600,
    min_score: float | None = None,
    url_contains: str | None = None,
    semantic: SemanticFn | None = None,
) -> list[dict[str, Any]]:
    """Packed pgvector chunks for an agent."""
    packed, _ = _pack_semantic(
        query,
        limit=limit,
        max_tokens=max_tokens,
        min_score=min_score,
        url_contains=url_contains,
        semantic=semantic,
    )
    return [as_agent_dict(hit) for hit in packed.kept]


def semantic_brief(
    query: str,
    *,
    limit: int = 5,
    max_tokens: int = 600,
    min_score: float | None = None,
    url_contains: str | None = None,
    semantic: SemanticFn | None = None,
) -> str:
    """Token-budgeted semantic-search brief."""
    packed, original = _pack_semantic(
        query,
        limit=limit,
        max_tokens=max_tokens,
        min_score=min_score,
        url_contains=url_contains,
        semantic=semantic,
    )
    return format_brief(packed, original)
