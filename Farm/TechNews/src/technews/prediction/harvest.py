"""Enrich news-trend topics with fresh web-search signal.

Wraps the WebSearch lane behind a small, never-raising boundary: each topic
becomes one query, the hits are reduced to a deduped top-5 title list, and any
backend failure degrades to ``hits=0`` with ``source="unavailable"``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

MAX_TITLES = 5
UNAVAILABLE = "unavailable"
_DEFAULT_SOURCE = "websearch.parallel"


@dataclass(frozen=True, slots=True)
class TopicSignal:
    """Reduced search signal for one news topic."""

    topic: str
    query: str
    hits: int
    top_titles: list[str]  # max 5, deduped
    source: str  # which backend produced the signal


def default_query(topic: str) -> str:
    """Build the default search query for a topic."""
    return f"{topic} news"


def top_titles(titles: list[str], *, limit: int = MAX_TITLES) -> list[str]:
    """Order-preserving case-insensitive dedupe, capped at ``limit``."""
    seen: set[str] = set()
    unique: list[str] = []
    for title in titles:
        key = " ".join(title.split()).casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(title)
        if len(unique) >= limit:
            break
    return unique


def _websearch_adapter(query: str) -> list:
    """Search through the WebSearch lane; imports lazily, raises to the boundary."""
    from WebSearch.frontend import parallel_search

    return parallel_search(query, limit=MAX_TITLES)


class TopicHarvester:
    """Check news topics against fresh web-search signal."""

    def __init__(self, search_fn: Callable[[str], list] | None = None) -> None:
        """search_fn defaults to a WebSearch-backed adapter (built lazily);
        inject a fake in tests/offline."""
        self._search_fn = search_fn
        self._warned = False

    def check_topic(self, topic: str, *, query: str | None = None) -> TopicSignal:
        """Return the search signal for one topic; never raises."""
        q = query if query is not None else default_query(topic)
        fn = self._search_fn if self._search_fn is not None else _websearch_adapter
        try:
            hits = fn(q)
        except Exception as exc:  # single degradation boundary, per contract
            if not self._warned:
                logger.warning(
                    "topic search unavailable (%s: %s); degrading to hits=0",
                    type(exc).__name__,
                    exc,
                )
                self._warned = True
            return TopicSignal(topic, q, 0, [], UNAVAILABLE)
        titles = [getattr(hit, "title", "") or "" for hit in hits]
        source = _DEFAULT_SOURCE if self._search_fn is None else "injected"
        return TopicSignal(topic, q, len(hits), top_titles(titles), source)

    def check_topics(self, topics: list[str]) -> list[TopicSignal]:
        """Check many topics, preserving order."""
        return [self.check_topic(topic) for topic in topics]


__all__ = [
    "MAX_TITLES",
    "TopicHarvester",
    "TopicSignal",
    "UNAVAILABLE",
    "default_query",
    "top_titles",
]
