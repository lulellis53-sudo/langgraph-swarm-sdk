"""Search result types shared by searchers, midend and benchmarks."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from WebSearch.frontend.providers import SearcherSpec
from WebSearch.urls import normalize_url

#: Search implementation signature: ``(query, spec) -> hits``.
SearchFn = Callable[[str, SearcherSpec], Sequence["SearchHit"]]


@dataclass(frozen=True, slots=True)
class SearchHit:
    title: str
    url: str
    snippet: str
    searcher_id: str
    #: Tokens the search API reported for the call; set on the first hit only.
    api_tokens: int = 0


class WebSearcher(Protocol):
    spec: SearcherSpec

    def search(self, query: str) -> Sequence[SearchHit]: ...


def type_is_hit(value: object) -> bool:
    """Return whether *value* is a ``SearchHit``.

    Args:
        value (object): Candidate object.

    Returns:
        bool: True if ``SearchHit``.
    """
    return isinstance(value, SearchHit)


def dedupe_hits(hits: Sequence[SearchHit]) -> list[SearchHit]:
    """Drop hits whose canonical URL was already seen; first occurrence wins.

    Args:
        hits (Sequence[SearchHit]): Hits in priority order.

    Returns:
        list[SearchHit]: Unique hits, order preserved.
    """
    seen: set[str] = set()
    unique: list[SearchHit] = []
    for hit in hits:
        key = normalize_url(hit.url)
        if key in seen:
            continue
        seen.add(key)
        unique.append(hit)
    return unique


__all__ = ["SearchFn", "SearchHit", "WebSearcher", "dedupe_hits", "type_is_hit"]
