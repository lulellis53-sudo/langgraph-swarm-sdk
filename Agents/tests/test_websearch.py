"""WebSearch contract smoke tests."""

from __future__ import annotations

from WebSearch.search import SEARCH_STACK, SearchHit, TypeRole, search_stack, type_is_hit


def test_search_stack_order() -> None:
    assert search_stack() == ("context7", "bright_data", "tavily")
    assert SEARCH_STACK[0] == "context7"


def test_search_hit_and_backend() -> None:
    hit = SearchHit(
        title="Example",
        url="https://example.com/docs",
        snippet="snippet",
        backend="context7",
    )
    assert type_is_hit(hit)
    assert TypeRole.ensure_backend("tavily") == "tavily"
