"""Agent-facing search tooling: one query in, one token-lean brief out.

Wraps the multi-provider pipeline for LLM agents: parallel search across
every configured provider, consensus-ranked (RRF), deduplicated by canonical
URL, then rendered as a numbered brief sized for a prompt budget. Agents that
prefer structured data use :func:`search_hits`; agents that want to paste
results straight into a prompt use :func:`search_brief`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from WebSearch.backend.normalize import normalize_text
from WebSearch.frontend.websearchers import (
    _SEARCH_CACHE_TTL_S,
    ProvidersConfig,
    SearchFn,
    SearchHit,
    parallel_search,
)
from WebSearch.repeater import normalize_url

_TITLE_CHARS = 120
_SNIPPET_CHARS = 200
_TAGS = re.compile(r"<[^>]+>")


def _plain(text: str) -> str:
    """Strip HTML tags, then normalize whitespace/entities/duplicate lines."""
    return normalize_text(_TAGS.sub(" ", text))


def search_hits(
    query: str,
    *,
    limit: int = 5,
    config: ProvidersConfig | None = None,
    backends: Mapping[str, SearchFn] | None = None,
    searcher_id: str | None = None,
    max_workers: int = 8,
    timeout_s: float = 30.0,
) -> list[SearchHit]:
    """One query, every provider in parallel, consensus-ranked unique hits.

    Thin convenience wrapper over :func:`parallel_search` with agent defaults
    (top-5, 30 s budget). See it for the full parameter docs.

    Args:
        query (str): User query (a dork string works as-is).
        limit (int): Max hits returned.
        config (ProvidersConfig | None): Registry; default ``load_providers()``.
        backends (Mapping[str, SearchFn] | None): id → callable; default HTTP APIs.
        searcher_id (str | None): Restrict to one searcher.
        max_workers (int): Thread cap.
        timeout_s (float): Overall wall-clock budget.

    Returns:
        list[SearchHit]: Unique hits, best (most providers agree) first.
    """
    return parallel_search(
        query,
        config=config,
        backends=backends,
        searcher_id=searcher_id,
        max_workers=max_workers,
        timeout_s=timeout_s,
        limit=limit,
        cache_ttl_s=_SEARCH_CACHE_TTL_S,
    )


def render_brief(
    hits: list[SearchHit], *, max_chars: int = 1200, snippet_chars: int = _SNIPPET_CHARS
) -> str:
    """Render hits as a numbered, token-lean brief for an agent prompt.

    Titles and snippets pass through :func:`normalize_text` (entities decoded,
    control chars dropped, repeated lines removed); URLs are canonicalized
    (no tracking params, no fragments). Lines stop once ``max_chars`` is
    reached; a ``Sources:`` footer lists the contributing searcher ids.

    Args:
        hits (list[SearchHit]): Merged hits (best first).
        max_chars (int): Soft cap on brief length (at least one hit is kept).
        snippet_chars (int): Per-hit snippet cap before normalization.

    Returns:
        str: The brief, or an empty string when ``hits`` is empty.
    """
    lines: list[str] = []
    sources: list[str] = []
    used = 0
    for index, hit in enumerate(hits, 1):
        title = _plain(hit.title)[:_TITLE_CHARS]
        snippet = _plain(hit.snippet[:snippet_chars])
        line = f"[{index}] {title} - {normalize_url(hit.url)}"
        if snippet:
            line = f"{line}\n    {snippet}"
        if lines and used + len(line) > max_chars:
            break
        lines.append(line)
        used += len(line) + 1
        if hit.searcher_id not in sources:
            sources.append(hit.searcher_id)
    if not lines:
        return ""
    return "\n".join(lines) + f"\nSources: {', '.join(sources)}"


def search_brief(
    query: str,
    *,
    limit: int = 5,
    max_chars: int = 1200,
    config: ProvidersConfig | None = None,
    backends: Mapping[str, SearchFn] | None = None,
    searcher_id: str | None = None,
    max_workers: int = 8,
    timeout_s: float = 30.0,
) -> str:
    """Search every provider with one query and return a prompt-ready brief.

    Args:
        query (str): User query (a dork string works as-is).
        limit (int): Max hits in the brief.
        max_chars (int): Soft cap on brief length.
        config (ProvidersConfig | None): Registry; default ``load_providers()``.
        backends (Mapping[str, SearchFn] | None): id → callable; default HTTP APIs.
        searcher_id (str | None): Restrict to one searcher.
        max_workers (int): Thread cap.
        timeout_s (float): Overall wall-clock budget.

    Returns:
        str: Numbered brief with canonical URLs and a ``Sources:`` footer.
    """
    hits = search_hits(
        query,
        limit=limit,
        config=config,
        backends=backends,
        searcher_id=searcher_id,
        max_workers=max_workers,
        timeout_s=timeout_s,
    )
    return render_brief(hits, max_chars=max_chars)


__all__ = ["render_brief", "search_brief", "search_hits"]
