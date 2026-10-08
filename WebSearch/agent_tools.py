"""Agent-facing search tooling: one query in, one token-lean brief out.

Wraps the multi-provider pipeline for LLM agents: parallel search across
every configured provider, consensus-ranked (RRF), deduplicated by canonical
URL, then rendered as a numbered brief sized for a prompt budget. Agents that
prefer structured data use :func:`search_hits`; agents that want to paste
results straight into a prompt use :func:`search_brief`.
"""

from __future__ import annotations

import asyncio
import os
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from WebSearch.backend.docs import ExtractedDoc
from WebSearch.backend.normalize import normalize_text
from WebSearch.backend.route import dedupe_normalize, semantic_handler
from WebSearch.frontend.websearchers import (
    _SEARCH_CACHE_TTL_S,
    ProvidersConfig,
    SearcherSpec,
    SearchFn,
    SearchHit,
    dedupe_hits,
    load_providers,
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


# --- status-reporting agent surface -------------------------------------------


#: Status values a searcher can report for one query.
STATUS_VALUES = ("ok", "empty", "no_key", "not_implemented", "disabled", "error")

_QUERY_RESULT_CACHE: OrderedDict[
    tuple[str, tuple[str, ...] | None, tuple[str, ...], tuple[str, ...]],
    tuple[float, SearchResult, ProvidersConfig, tuple[tuple[str, SearchFn], ...]],
] = OrderedDict()
_QUERY_RESULT_CACHE_LOCK = threading.Lock()
_QUERY_RESULT_CACHE_MAX = 128


@dataclass(frozen=True, slots=True)
class SearcherStatus:
    """One searcher's outcome for one query: a status plus a short human hint."""

    status: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Query result with per-searcher status: hits plus why a searcher contributed none.

    Attributes:
        query: The query as passed in.
        hits: Merged unique hits, config order, best first.
        status: searcher id → why it did or did not contribute.
        timings_ms: searcher id → wall time of its backend call.
        tokens: Sum of per-hit API token usage (0 for keyless and cached hits).
    """

    query: str
    hits: tuple[SearchHit, ...] = ()
    status: dict[str, SearcherStatus] = field(default_factory=dict)
    timings_ms: dict[str, float] = field(default_factory=dict)
    tokens: int = 0


def _searcher_enabled(spec: SearcherSpec, enabled_ids: Sequence[str] | None) -> bool:
    """Runtime decision: ``enabled_ids`` overrides the YAML ``enabled`` flag."""
    if enabled_ids is not None:
        return spec.id in enabled_ids
    return spec.enabled


def _query_cache_key(
    query: str,
    cfg: ProvidersConfig,
    backends: Mapping[str, SearchFn] | None,
    enabled_ids: Sequence[str] | None,
) -> tuple[str, tuple[str, ...] | None, tuple[str, ...], tuple[str, ...]]:
    return (
        query,
        tuple(sorted(enabled_ids)) if enabled_ids is not None else None,
        tuple(spec.id for spec in cfg.searchers),
        tuple(sorted(backends or {})),
    )


def _cached_result(
    key: tuple[str, tuple[str, ...] | None, tuple[str, ...], tuple[str, ...]],
    ttl_s: float,
    cfg: ProvidersConfig,
    backends: Mapping[str, SearchFn] | None,
) -> SearchResult | None:
    """Live cache entry for *key* whose config and backends are still the same objects."""
    now = time.monotonic()
    with _QUERY_RESULT_CACHE_LOCK:
        entry = _QUERY_RESULT_CACHE.get(key)
        if entry is None:
            return None
        expires_at, result, entry_cfg, entry_fns = entry
        if (
            now >= expires_at
            or entry_cfg is not cfg
            or any(backends is not None and backends.get(sid) is not fn for sid, fn in entry_fns)
        ):
            del _QUERY_RESULT_CACHE[key]
            return None
        _QUERY_RESULT_CACHE.move_to_end(key)
        return result


def _store_result(
    key: tuple[str, tuple[str, ...] | None, tuple[str, ...], tuple[str, ...]],
    ttl_s: float,
    result: SearchResult,
    cfg: ProvidersConfig,
    backends: Mapping[str, SearchFn] | None,
) -> None:
    with _QUERY_RESULT_CACHE_LOCK:
        while len(_QUERY_RESULT_CACHE) >= _QUERY_RESULT_CACHE_MAX:
            _QUERY_RESULT_CACHE.popitem(last=False)
        _QUERY_RESULT_CACHE[key] = (
            time.monotonic() + ttl_s,
            result,
            cfg,
            tuple((sid, fn) for sid, fn in (backends or {}).items()),
        )


def search(
    query: str,
    *,
    config: ProvidersConfig | None = None,
    backends: Mapping[str, SearchFn] | None = None,
    enabled_ids: Sequence[str] | None = None,
    limit: int = 0,
    cache_ttl_s: float = _SEARCH_CACHE_TTL_S,
) -> SearchResult:
    """Run every enabled searcher and report why each one did or did not contribute.

    Searchers disabled in the registry (or outside ``enabled_ids``) are never
    called and report ``disabled``. An enabled searcher whose API key env vars
    all resolve empty reports ``no_key``; one without a registered backend
    reports ``not_implemented``. A backend that runs reports ``ok`` with hits
    or ``empty`` without, and a backend that raises reports ``error`` and never
    affects the other searchers.

    Results are cached per (query, config, backends, enabled_ids) for
    ``cache_ttl_s`` seconds (LRU, identity-checked so a rebuilt config or
    backend set is a different entry); ``<= 0`` disables the cache.

    Args:
        query (str): User query (a dork string works as-is).
        config (ProvidersConfig | None): Registry; default ``load_providers()``.
        backends (Mapping[str, SearchFn] | None): id → callable; default HTTP APIs.
        enabled_ids (Sequence[str] | None): When given, only these ids run.
        limit (int): Max merged hits; ``0`` returns everything.
        cache_ttl_s (float): Query-result cache lifetime in seconds.

    Returns:
        SearchResult: Unique hits plus per-searcher status, timings and tokens.
    """
    cfg = config if config is not None else load_providers()
    key = _query_cache_key(query, cfg, backends, enabled_ids)
    if cache_ttl_s > 0 and (cached := _cached_result(key, cache_ttl_s, cfg, backends)):
        return cached

    table = dict(backends) if backends is not None else {}
    hits: list[SearchHit] = []
    statuses: dict[str, SearcherStatus] = {}
    timings: dict[str, float] = {}
    for spec in cfg.searchers:
        if not _searcher_enabled(spec, enabled_ids):
            reason = "not in enabled_ids" if enabled_ids is not None else "enabled: false"
            statuses[spec.id] = SearcherStatus("disabled", reason)
            continue
        key_names = [spec.api_key_env, *spec.api_key_fallback_envs]
        if any(name for name in key_names) and not any(
            os.environ.get(name, "").strip() for name in key_names
        ):
            statuses[spec.id] = SearcherStatus(
                "no_key", f"set {spec.api_key_env or key_names[-1]} to enable"
            )
            continue
        fn = table.get(spec.id)
        if fn is None:
            statuses[spec.id] = SearcherStatus("not_implemented", "no backend registered")
            continue
        started = time.perf_counter()
        try:
            batch = list(fn(query, spec))
        except Exception as exc:  # status, not crash: one searcher never breaks the query
            timings[spec.id] = (time.perf_counter() - started) * 1000.0
            statuses[spec.id] = SearcherStatus("error", str(exc)[:120])
            continue
        timings[spec.id] = (time.perf_counter() - started) * 1000.0
        hits.extend(batch)
        statuses[spec.id] = SearcherStatus("ok" if batch else "empty")
    merged = dedupe_hits(hits)
    if limit and limit > 0:
        merged = merged[:limit]
    result = SearchResult(
        query=query,
        hits=tuple(merged),
        status=statuses,
        timings_ms=timings,
        tokens=sum(hit.api_tokens for hit in merged),
    )
    if cache_ttl_s > 0:
        _store_result(key, cache_ttl_s, result, cfg, backends)
    return result


async def asearch(
    query: str,
    *,
    config: ProvidersConfig | None = None,
    backends: Mapping[str, SearchFn] | None = None,
    enabled_ids: Sequence[str] | None = None,
    limit: int = 0,
    cache_ttl_s: float = _SEARCH_CACHE_TTL_S,
) -> SearchResult:
    """Awaitable :func:`search` — the blocking run happens in a worker thread."""
    return await asyncio.to_thread(
        search,
        query,
        config=config,
        backends=backends,
        enabled_ids=enabled_ids,
        limit=limit,
        cache_ttl_s=cache_ttl_s,
    )


def as_tool(
    *,
    config: ProvidersConfig | None = None,
    backends: Mapping[str, SearchFn] | None = None,
    enabled_ids: Sequence[str] | None = None,
    limit: int = 5,
    max_tokens: int = 200,
    count_tokens: Callable[[str], int] | None = None,
) -> Callable[[str], str]:
    """Bind :func:`search` into a plain ``(query) -> brief`` callable for an agent.

    The brief is :func:`render_brief` output over the merged hits, trimmed to
    ``max_tokens`` when a ``count_tokens`` counter is supplied (default counter:
    none, and the brief is only bounded by ``render_brief``'s character cap of
    four characters per token).

    Args:
        config (ProvidersConfig | None): Registry; default ``load_providers()``.
        backends (Mapping[str, SearchFn] | None): id → callable; default none.
        enabled_ids (Sequence[str] | None): When given, only these ids run.
        limit (int): Max hits in a brief.
        max_tokens (int): Prompt budget for the brief.
        count_tokens (Callable[[str], int] | None): Token counter for trimming.

    Returns:
        Callable[[str], str]: Query → cited, prompt-ready brief string.
    """

    def tool(query: str) -> str:
        result = search(
            query, config=config, backends=backends, enabled_ids=enabled_ids, limit=limit
        )
        brief = render_brief(list(result.hits)[:limit], max_chars=max_tokens * 4)
        if count_tokens is None or count_tokens(brief) <= max_tokens:
            return brief
        lines = brief.splitlines()
        while len(lines) > 2 and count_tokens("\n".join(lines)) > max_tokens:
            lines = lines[:-1]
        return "\n".join(lines)

    return tool


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
    "STATUS_VALUES",
    "SearchResult",
    "SearcherStatus",
    "asearch",
    "as_tool",
    "dedupe_documents",
    "render_brief",
    "search",
    "search_brief",
    "search_hits",
    "summarize_documents",
]
