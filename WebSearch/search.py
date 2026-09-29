"""WebSearch backend contract.

Cursor agents run the live stack (Context7 → Bright Data → Tavily). This module
only names backends and hit shapes so other code can import a stable contract.
It does not open sockets or read API keys.
"""

from __future__ import annotations

from typing import Literal, NamedTuple

SearchBackend = Literal["context7", "bright_data", "tavily"]

SEARCH_STACK: tuple[SearchBackend, ...] = ("context7", "bright_data", "tavily")


class SearchHit(NamedTuple):
    title: str
    url: str
    snippet: str
    backend: SearchBackend


class TypeRole:
    @staticmethod
    def ensure_backend(value: object) -> SearchBackend:
        if value == "context7" or value == "bright_data" or value == "tavily":
            return value
        raise TypeError(f"unknown search backend: {value!r}")


def type_is_hit(value: object) -> bool:
    return isinstance(value, SearchHit)


def search_stack() -> tuple[SearchBackend, ...]:
    return SEARCH_STACK


__all__ = [
    "SEARCH_STACK",
    "SearchBackend",
    "SearchHit",
    "TypeRole",
    "search_stack",
    "type_is_hit",
]
