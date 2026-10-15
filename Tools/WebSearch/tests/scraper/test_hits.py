"""Tests for hit cleanup, compact packing, and LangChain tool bindings."""

from __future__ import annotations

from typing import Any

from WebSearch.scraper.agent_tools import search_brief, search_hits, semantic_brief, semantic_hits
from WebSearch.scraper.hits import (
    as_agent_dict,
    canonicalize_url,
    compact_hits,
    format_brief,
    hit_score,
    prepare_hits,
    prune_snippet_to_query,
)


def _raw(title: str, url: str, content: str) -> dict[str, Any]:
    return {"title": title, "url": url, "content": content}


def test_canonicalize_strips_tracking_and_slash() -> None:
    url = "https://WWW.Shop.Example/item/?utm_source=x&id=1#frag"
    assert canonicalize_url(url) == "https://shop.example/item?id=1"


def test_canonicalize_leaves_bare_ids() -> None:
    assert canonicalize_url("u") == "u"


def test_prune_keeps_query_sentences() -> None:
    snippet = (
        "Shipping is free worldwide this week. "
        "LangGraph orchestration for multi-agent workflows. "
        "Buy banana bread mix on sale."
    )
    out = prune_snippet_to_query(snippet, "langgraph orchestration", max_chars=80)
    assert "LangGraph" in out
    assert "banana bread" not in out


def test_hit_score_ignores_stopwords() -> None:
    score = hit_score(
        "LangGraph docs",
        "orchestration for agents",
        "the langgraph orchestration",
    )
    assert score == 1.0


def test_prepare_dedupes_canonical_urls_and_strips_site() -> None:
    raw = [
        _raw("LangGraph | Example", "https://example.com/a?utm_campaign=x", "LangGraph intro"),
        _raw("LangGraph | Example", "https://example.com/a/", "duplicate page"),
    ]
    prepared = prepare_hits(raw, "langgraph")
    assert len(prepared) == 1
    assert prepared[0]["url"] == "https://example.com/a"
    assert prepared[0]["title"] == "LangGraph"


def test_compact_hits_respects_token_budget() -> None:
    raw = [
        _raw(f"topic {i}", f"https://ex.test/{i}", ("alpha bravo charlie " * 40) + f" unique{i}")
        for i in range(8)
    ]
    result = compact_hits(raw, "alpha bravo", budget_tokens=80, limit=8)
    assert result.kept
    assert result.tokens_used <= 80
    brief = format_brief(result, len(raw))
    assert brief.startswith("[")
    assert "](https://ex.test/" in brief
    assert "kept " in brief


def test_min_score_filters_off_target() -> None:
    raw = [
        _raw(
            "LangGraph orchestration",
            "https://ex.test/lg",
            "Low-level multi-agent orchestration.",
        ),
        _raw("Banana bread", "https://ex.test/food", "Moist banana bread with walnuts."),
    ]
    result = compact_hits(raw, "langgraph orchestration", budget_tokens=400, min_score=0.3)
    assert [hit["url"] for hit in result.kept] == ["https://ex.test/lg"]


def _fetch(_query: str, _limit: int) -> list[dict[str, Any]]:
    return [
        _raw(
            "LangGraph orchestration",
            "https://langchain.github.io/langgraph/",
            "Low-level orchestration for multi-agent workflows.",
        ),
        _raw(
            "Banana bread recipes",
            "https://recipes.example/banana-bread",
            "Moist banana bread with walnuts.",
        ),
    ]


def test_agent_search_brief_and_hits() -> None:
    brief = search_brief("langgraph orchestration", fetch=_fetch, min_score=0.3)
    assert "LangGraph" in brief
    assert "banana" not in brief.lower()
    packed = search_hits("langgraph orchestration", fetch=_fetch, min_score=0.3)
    assert packed[0]["url"] == "https://langchain.github.io/langgraph"
    assert packed[0] == as_agent_dict(packed[0])
    assert set(packed[0]) == {"title", "url", "snippet", "score", "source"}


def _semantic(_query: str, _limit: int, _url: str | None) -> list[dict[str, Any]]:
    return [
        {
            "title": "https://docs.example/a#0",
            "url": "https://docs.example/a",
            "snippet": "LangGraph is a low-level orchestration framework for agents.",
            "score": 0.9,
            "chunk_idx": 0,
            "source": "pgvector",
        },
        {
            "title": "https://docs.example/b#0",
            "url": "https://docs.example/b",
            "snippet": "Banana bread recipe with walnuts and honey.",
            "score": 0.2,
            "chunk_idx": 0,
        },
    ]


def test_agent_semantic_pack() -> None:
    brief = semantic_brief("langgraph orchestration", semantic=_semantic, min_score=0.3)
    assert "LangGraph" in brief
    packed = semantic_hits("langgraph orchestration", semantic=_semantic, min_score=0.3)
    assert packed[0]["url"] == "https://docs.example/a"
    assert packed[0]["source"] == "pgvector"
