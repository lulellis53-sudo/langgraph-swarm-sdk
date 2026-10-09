"""Process-local LRU and optional Redis caching for search results."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import TYPE_CHECKING

from WebSearch.frontend.types import SearcherSpec

if TYPE_CHECKING:
    from WebSearch.frontend.types import SearchHit

logger = logging.getLogger(__name__)

_SEARCH_CACHE_TTL_S = 300.0
_SEARCH_CACHE_MAX = 256
_SEARCH_CACHE: OrderedDict[tuple[str, str, int], tuple[float, list[SearchHit], object]] = (
    OrderedDict()
)
_SEARCH_CACHE_LOCK = threading.Lock()
_REDIS_SEARCH_CACHE_LOCK = threading.Lock()
_REDIS_SEARCH_CACHE_URL = ""
_REDIS_SEARCH_CACHE: object = None

#: Search backend signature; ``object`` avoids a circular import at runtime.
#: The real shape is ``Callable[[str, SearcherSpec], list[SearchHit]]``.
SearchFn = (
    object  # Avoid circular import; actual type is Callable[[str, SearcherSpec], list[SearchHit]]
)


def _redis_search_cache():
    """Return the shared Redis search cache when REDIS_URL is configured."""
    global _REDIS_SEARCH_CACHE, _REDIS_SEARCH_CACHE_URL
    url = os.environ.get("REDIS_URL", "").strip()
    if not url:
        return None
    if url != _REDIS_SEARCH_CACHE_URL:
        with _REDIS_SEARCH_CACHE_LOCK:
            if url != _REDIS_SEARCH_CACHE_URL:
                from swarm_sdk.retrieval.redis_exact import RedisExactCache

                _REDIS_SEARCH_CACHE = RedisExactCache(url, "websearch:results", 300)
                _REDIS_SEARCH_CACHE_URL = url
    return _REDIS_SEARCH_CACHE


def _redis_search_key(spec: SearcherSpec, fn: object, query: str) -> str:
    """Build a stable identity from provider configuration and exact query text."""
    module = getattr(fn, "__module__", type(fn).__module__)
    name = getattr(fn, "__qualname__", type(fn).__qualname__)
    function = f"{module}.{name}"
    return "\n".join(
        (
            spec.id,
            function,
            spec.kind,
            spec.engine or "",
            spec.base_url or "",
            spec.base_url_env or "",
            query,
        )
    )


def _encode_search_hits(hits: Sequence) -> str:
    """Serialize compact search hit records, excluding per-call API token usage."""
    return json.dumps(
        [
            {
                "title": hit.title,
                "url": hit.url,
                "snippet": hit.snippet,
                "searcher_id": hit.searcher_id,
                "also_from": hit.also_from,
            }
            for hit in hits
        ],
        separators=(",", ":"),
    )


def _decode_search_hits(value: str) -> list | None:
    """Deserialize search hits, rejecting malformed cache values as misses."""
    from WebSearch.frontend.types import SearchHit

    try:
        rows = json.loads(value)
    except json.JSONDecodeError:
        return None
    if not isinstance(rows, list):
        return None
    hits: list[SearchHit] = []
    for row in rows:
        if not isinstance(row, dict) or not all(
            isinstance(row.get(field), str) for field in ("title", "url", "snippet", "searcher_id")
        ):
            return None
        also_from = row.get("also_from", ())
        if not isinstance(also_from, (list, tuple)) or not all(
            isinstance(item, str) for item in also_from
        ):
            return None
        hits.append(
            SearchHit(
                title=row["title"],
                url=row["url"],
                snippet=row["snippet"],
                searcher_id=row["searcher_id"],
                also_from=tuple(also_from),
            )
        )
    return hits


def _search_cache_get(searcher_id: str, query: str, fn: object) -> list | None:
    """Live cached hits for this (searcher, query) pair, or ``None``."""
    now = time.monotonic()
    with _SEARCH_CACHE_LOCK:
        key = (searcher_id, query, id(fn))
        entry = _SEARCH_CACHE.get(key)
        if entry is None:
            return None
        expires_at, hits, cached_fn = entry
        if now >= expires_at or cached_fn is not fn:
            del _SEARCH_CACHE[key]
            return None
        _SEARCH_CACHE.move_to_end(key)
        return hits


def _search_cache_put(searcher_id: str, query: str, fn: object, hits: list, ttl_s: float) -> None:
    """Store hits with ``api_tokens`` zeroed: a cache hit costs no API call."""
    with _SEARCH_CACHE_LOCK:
        while len(_SEARCH_CACHE) >= _SEARCH_CACHE_MAX:
            _SEARCH_CACHE.popitem(last=False)
        _SEARCH_CACHE[(searcher_id, query, id(fn))] = (
            time.monotonic() + ttl_s,
            [replace(hit, api_tokens=0) for hit in hits],
            fn,
        )


def cached_provider_search(
    spec: SearcherSpec,
    query: str,
    fn: object,
    ttl_s: float,
) -> list:
    """Run one provider search with process-local and optional Redis caching."""
    if ttl_s <= 0:
        return list(fn(query, spec))
    cached = _search_cache_get(spec.id, query, fn)
    if cached is not None:
        return cached

    redis_cache = _redis_search_cache()
    redis_key = _redis_search_key(spec, fn, query)
    if redis_cache is not None:
        encoded = redis_cache.get(redis_key)
        if encoded is not None:
            cached = _decode_search_hits(encoded)
            if cached is not None:
                _search_cache_put(spec.id, query, fn, cached, ttl_s)
                return cached

    hits = list(fn(query, spec))
    _search_cache_put(spec.id, query, fn, hits, ttl_s)
    if redis_cache is not None:
        redis_cache.set(
            redis_key,
            _encode_search_hits(hits),
            ttl_s=max(1, int(ttl_s)),
        )
    return hits
