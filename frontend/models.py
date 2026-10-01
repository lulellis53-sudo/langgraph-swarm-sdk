"""Search result types shared by searchers, midend and benchmarks."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from WebSearch.frontend.providers import SearcherSpec
from WebSearch.repeater import normalize_url

#: Search implementation signature: ``(query, spec) -> hits``.
SearchFn = Callable[[str, SearcherSpec], Sequence["SearchHit"]]


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One search result from one searcher."""

    title: str
    url: str
    snippet: str
    searcher_id: str
    #: Tokens the search API reported for the call; set on the first hit only.
    api_tokens: int = 0
    #: Searcher ids whose near-duplicate hit was merged into this one.
    also_from: tuple[str, ...] = ()


class WebSearcher(Protocol):
    """A searcher bound to its registry spec."""

    spec: SearcherSpec

    def search(self, query: str) -> Sequence[SearchHit]: ...


@dataclass(frozen=True, slots=True)
class SinkReport:
    """Outcome of one :meth:`ResultSink.store` call.

    ``detail`` is free text the sink may use to say how it ran; WebSearch never
    interprets it.
    """

    stored: int
    skipped: int = 0
    detail: str = ""


class ResultSink(Protocol):
    """Receives the final, cleaned hits (for example to index them)."""

    def store(self, hits: Sequence[SearchHit]) -> SinkReport: ...


class NullSink:
    """Sink that stores nothing."""

    def store(self, hits: Sequence[SearchHit]) -> SinkReport:
        """Return a zero-count report without persisting hits."""
        return SinkReport(stored=0)


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


__all__ = [
    "NullSink",
    "ResultSink",
    "SearchFn",
    "SearchHit",
    "SinkReport",
    "WebSearcher",
    "dedupe_hits",
    "type_is_hit",
]
