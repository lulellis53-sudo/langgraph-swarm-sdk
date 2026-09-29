"""In-repo live-web research feature. Runtime contract: ``WebSearch.search``."""

from __future__ import annotations

from .search import SEARCH_STACK, SearchHit, search_stack, type_is_hit

__all__ = ["SEARCH_STACK", "SearchHit", "search_stack", "type_is_hit"]
