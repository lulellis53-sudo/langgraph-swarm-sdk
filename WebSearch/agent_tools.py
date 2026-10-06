"""Agent-facing search tooling: one query in, one token-lean brief out.

Wraps the multi-provider pipeline for LLM agents: parallel search across
every configured provider, consensus-ranked (RRF), deduplicated by canonical
URL, then rendered as a numbered brief sized for a prompt budget. Agents that
prefer structured data use :func:`search_hits`; agents that want to paste
results straight into a prompt use :func:`search_brief`.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, replace
from typing import Any

import tiktoken

from WebSearch.backend.docs import ExtractedDoc
from WebSearch.backend.normalize import normalize_text
from WebSearch.backend.route import dedupe_normalize, semantic_handler
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


#: Encoding used for prompt budgeting. cl100k_base matches the GPT-4/3.5 family and is
#: the closest widely-available proxy for "tokens an agent will pay" across providers.
_ENCODING_NAME = "cl100k_base"


@functools.cache
def _encoding() -> tiktoken.Encoding:
    """Return the shared tokenizer, loading it once per process."""
    return tiktoken.get_encoding(_ENCODING_NAME)


def count_tokens(text: str) -> int:
    """Count tokens in ``text`` with tiktoken (cl100k_base).

    Prompt budgets are paid in tokens, not characters: a char cap under-counts
    CJK/emoji text and over-counts short English words.

    Args:
        text (str): Any string; empty input counts as zero.

    Returns:
        int: Token count.
    """
    if not text:
        return 0
    return len(_encoding().encode(text, disallowed_special=()))


_WORD = re.compile(r"\w+")


def relevance_score(hit: SearchHit, query: str) -> float:
    """Score one hit against the query as a Jaccard overlap of query terms.

    Deliberately lexical and dependency-free: it runs on every hit on every
    search, so it must be cheap and deterministic. It is a *ranking and gating*
    signal, not a semantic embedding; use :func:`WebSearch.backend.semantic.summarize_score`
    when real semantic similarity is needed.

    Args:
        hit (SearchHit): The hit to score.
        query (str): The user query.

    Returns:
        float: Overlap in ``[0.0, 1.0]``; 0.0 for an empty query.
    """
    terms = {t for t in _WORD.findall(query.casefold()) if len(t) > 1}
    if not terms:
        return 0.0
    haystack = {t for t in _WORD.findall(f"{hit.title} {hit.snippet}".casefold()) if len(t) > 1}
    if not haystack:
        return 0.0
    return len(terms & haystack) / len(terms)


def score_hits(hits: list[SearchHit], query: str) -> list[SearchHit]:
    """Return copies of ``hits`` with their ``query`` and ``relevance`` filled in.

    Per-result scoring makes a ranking auditable after the fact: an agent (or a
    test) can see *why* a hit was ordered where it was, rather than trusting the
    merged order. The input list and its hits are never mutated.

    Args:
        hits (list[SearchHit]): Hits to score.
        query (str): The query they were retrieved for.

    Returns:
        list[SearchHit]: New hits carrying ``query`` and ``relevance``.
    """
    return [replace(h, query=query, relevance=relevance_score(h, query)) for h in hits]


def rank_hits(hits: list[SearchHit], query: str) -> list[SearchHit]:
    """Reorder hits by query relevance, keeping provider-consensus order as the tiebreak.

    Python's sort is stable, so hits with equal scores keep their incoming order
    — which is already RRF-consensus ranked by the search layer.

    Args:
        hits (list[SearchHit]): Merged hits.
        query (str): The user query.

    Returns:
        list[SearchHit]: All hits, most relevant first.
    """
    if not query.strip():
        return list(hits)
    return sorted(hits, key=lambda h: -(h.relevance or relevance_score(h, query)))


def tokens_saved(before: str, after: str) -> int:
    """Tokens (cl100k_base) that ``after`` saves versus ``before``; never negative.

    Lets a caller log the budget win of a tighter brief instead of guessing.

    Args:
        before (str): The baseline text (for example a generous brief).
        after (str): The tightened text.

    Returns:
        int: Tokens saved, floored at zero.
    """
    return max(0, count_tokens(before) - count_tokens(after))


def render_brief(
    hits: list[SearchHit],
    *,
    max_tokens: int = 400,
    max_chars: int | None = None,
    snippet_chars: int = _SNIPPET_CHARS,
    query: str = "",
    min_score: float | None = None,
    show_scores: bool = False,
) -> str:
    """Render hits as a numbered, token-budgeted brief for an agent prompt.

    Titles and snippets pass through :func:`normalize_text` (entities decoded,
    control chars dropped, repeated lines removed); URLs are canonicalized (no
    tracking params, no fragments). Hits are ranked by relevance to ``query``
    first, optionally filtered by ``min_score``, then added until the tiktoken
    budget is reached. At least one hit is always kept: a brief that says
    nothing is worse than one that overruns slightly.

    Args:
        hits (list[SearchHit]): Merged hits (best first).
        max_tokens (int): Soft cap measured with tiktoken (cl100k_base).
        max_chars (int | None): Deprecated character cap; when set it applies in
            addition to ``max_tokens`` so existing callers keep their bound.
        snippet_chars (int): Per-hit snippet cap before normalization.
        query (str): Enables relevance ranking; empty keeps incoming order.
        min_score (float | None): Drop hits scoring below this (0..1). The best
            hit survives even if it fails the threshold.
        show_scores (bool): Annotate each line with its relevance score. Costs
            a few tokens per hit; useful when debugging retrieval quality.

    Returns:
        str: The brief, or an empty string when ``hits`` is empty.

    Raises:
        ValueError: If ``max_tokens`` or ``max_chars`` is not positive.
    """
    if max_tokens < 1:
        raise ValueError("max_tokens must be >= 1")
    if max_chars is not None and max_chars < 1:
        raise ValueError("max_chars must be >= 1")
    if not hits:
        return ""

    ordered = rank_hits(list(hits), query)
    if min_score is not None and query.strip():
        kept = [h for h in ordered if relevance_score(h, query) >= min_score]
        ordered = kept or ordered[:1]

    lines: list[str] = []
    sources: list[str] = []
    used = 0
    for index, hit in enumerate(ordered, 1):
        title = _plain(hit.title)[:_TITLE_CHARS]
        snippet = _plain(hit.snippet[:snippet_chars])
        score = hit.relevance or relevance_score(hit, query)
        marker = f" (score={score:.2f})" if show_scores else ""
        line = f"[{index}] {title}{marker} - {normalize_url(hit.url)}"
        if snippet:
            line = f"{line}\n    {snippet}"
        # The footer is emitted after the hits, so reserve its cost: budgeting
        # only the lines lets the brief overshoot ``max_tokens`` on the footer.
        next_sources = sources if hit.searcher_id in sources else [*sources, hit.searcher_id]
        footer_tokens = count_tokens(f"\nSources: {', '.join(next_sources)}")
        prospective = used + count_tokens(line) + 1 + footer_tokens
        over_tokens = bool(lines) and prospective > max_tokens
        over_chars = max_chars is not None and bool(lines) and used + len(line) > max_chars
        if over_tokens or over_chars:
            break
        lines.append(line)
        used = prospective - footer_tokens
        sources = next_sources

    return "\n".join(lines) + f"\nSources: {', '.join(sources)}"


def search_brief(
    query: str,
    *,
    limit: int = 5,
    max_tokens: int = 400,
    max_chars: int | None = None,
    min_score: float | None = None,
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
    return render_brief(
        hits, max_tokens=max_tokens, max_chars=max_chars, query=query, min_score=min_score
    )


def dedupe_documents(docs: Sequence[ExtractedDoc]) -> dict[str, Any]:
    """Normalize and deduplicate extracted documents for agent workflows."""
    clean = dedupe_normalize(docs)
    return {
        "action": "dedupe",
        "input": len(docs),
        "kept": len(clean),
        "removed": len(docs) - len(clean),
        "documents": [asdict(doc) for doc in clean],
    }


def summarize_documents(
    query: str,
    docs: Sequence[ExtractedDoc],
    *,
    max_results: int = 10,
) -> dict[str, Any]:
    """Rank normalized documents with the semantic vector index and summarize them."""
    if not query.strip():
        raise ValueError("query is required for summarize")
    if max_results < 1:
        raise ValueError("max_results must be >= 1")
    clean = dedupe_normalize(docs)
    detail = semantic_handler(query, db_path=":memory:")(clean)
    return {
        "action": "summarize",
        "count": len(clean),
        "embedding": detail["embedding"],
        "results": detail["summaries"][:max_results],
    }


__all__ = [
    "count_tokens",
    "dedupe_documents",
    "rank_hits",
    "score_hits",
    "tokens_saved",
    "relevance_score",
    "render_brief",
    "search_brief",
    "search_hits",
    "summarize_documents",
]
