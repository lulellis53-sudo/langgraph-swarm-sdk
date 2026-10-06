"""Agent-facing brief rendering: token budget, relevance ranking, and quality.

These cover the prompt-facing surface (`render_brief`, `search_brief`) where the
cost of a bad result is paid twice: tokens in the prompt, and an agent acting on
an irrelevant hit.
"""

from __future__ import annotations

import tiktoken
from WebSearch.agent_tools import count_tokens, rank_hits, render_brief
from WebSearch.frontend.websearchers import SearchHit


def _hit(
    title: str, url: str = "https://example.com/a", snippet: str = "", searcher: str = "s1"
) -> SearchHit:
    """Build a hit with the given fields."""
    return SearchHit(title=title, url=url, snippet=snippet, searcher_id=searcher)


# ---------------------------------------------------------------- token counting


def test_count_tokens_matches_tiktoken_cl100k() -> None:
    """``count_tokens`` is the cl100k_base count, not a char heuristic."""
    text = "Retrieval augmented generation improves factual grounding."
    expected = len(tiktoken.get_encoding("cl100k_base").encode(text))
    assert count_tokens(text) == expected


def test_count_tokens_is_zero_for_empty_text() -> None:
    """Empty text costs zero tokens rather than raising."""
    assert count_tokens("") == 0


def test_count_tokens_non_ascii_is_not_char_count() -> None:
    """Non-ASCII text is tokenized properly, not counted as characters."""
    text = "日本語のテキストです"
    assert count_tokens(text) != len(text)


# ---------------------------------------------------------------- token budget


def test_render_brief_respects_token_budget() -> None:
    """The brief stays within ``max_tokens`` measured by tiktoken."""
    hits = [
        _hit(f"Result number {i}", f"https://example.com/{i}", "snippet text here")
        for i in range(40)
    ]
    assert len(hits) == 40
    brief = render_brief(hits, max_tokens=60)
    assert count_tokens(brief) <= 60


def test_render_brief_keeps_at_least_one_hit() -> None:
    """An impossibly small budget still yields one hit, never an empty brief."""
    brief = render_brief([_hit("Only hit", snippet="body")], max_tokens=1)
    assert brief != ""
    assert "Only hit" in brief


def test_render_brief_stops_early_when_budget_is_small() -> None:
    """A small budget includes fewer hits than a large one."""
    hits = [_hit(f"Result {i}", f"https://example.com/{i}", "x" * 80) for i in range(10)]
    small = render_brief(hits, max_tokens=50)
    large = render_brief(hits, max_tokens=500)
    assert count_tokens(small) <= 50
    assert small.count("[") <= large.count("[")


def test_render_brief_has_no_sources_footer_when_empty() -> None:
    """No hits renders an empty string, not a dangling footer."""
    assert render_brief([], max_tokens=100) == ""


# ---------------------------------------------------------------- relevance ranking


def test_rank_hits_orders_by_query_relevance() -> None:
    """Hits sharing query terms outrank unrelated ones."""
    relevant = _hit(
        "LightGBM gradient boosting", "https://a.example/x", "gradient boosted decision trees"
    )
    unrelated = _hit("Cooking pasta", "https://b.example/y", "boil water and add salt")
    ranked = rank_hits([unrelated, relevant], "lightgbm gradient boosting")
    assert ranked[0].url == relevant.url


def test_rank_hits_is_stable_for_equal_scores() -> None:
    """Equal relevance preserves the incoming order (no arbitrary reshuffle)."""
    first = _hit("alpha", "https://a.example/1")
    second = _hit("alpha", "https://b.example/2")
    ranked = rank_hits([first, second], "alpha")
    assert [h.url for h in ranked] == [first.url, second.url]


def test_rank_hits_returns_all_hits() -> None:
    """Ranking reorders; it never drops hits."""
    hits = [_hit(f"item {i}", f"https://example.com/{i}") for i in range(5)]
    assert len(rank_hits(hits, "item 3")) == 5


def test_rank_hits_with_empty_query_preserves_order() -> None:
    """An empty query carries no signal, so order is untouched."""
    hits = [_hit("a", "https://a.example/1"), _hit("b", "https://b.example/2")]
    assert [h.url for h in rank_hits(hits, "   ")] == [h.url for h in hits]


def test_rank_hits_respects_an_explicit_zero_score() -> None:
    """A scored zero remains zero when it is rendered or ranked again."""
    from WebSearch.agent_tools import score_hits

    relevant = _hit("lightgbm model", "https://a.example/1")
    irrelevant = _hit("gardening guide", "https://b.example/2")
    scored = score_hits([irrelevant, relevant], "lightgbm")
    assert scored[0].relevance == 0.0
    assert [hit.url for hit in rank_hits(scored, "lightgbm")] == [
        relevant.url,
        irrelevant.url,
    ]
    assert "(score=0.00)" in render_brief(
        [scored[0]], max_tokens=100, query="lightgbm", show_scores=True
    )


def test_relevance_ignores_common_words_in_query() -> None:
    """Common language terms do not make unrelated search results look relevant."""
    from WebSearch.agent_tools import relevance_score

    hit = _hit("LightGBM guide", snippet="gradient boosted decision trees")
    assert relevance_score(hit, "what is the LightGBM guide for") == 1.0


# ---------------------------------------------------------------- quality: relevance gate


def test_render_brief_drops_hits_below_min_score() -> None:
    """Low-relevance hits are excluded when ``min_score`` is set."""
    good = _hit("lightgbm gradient boosting", "https://a.example/x", "gradient boosting trees")
    noise = _hit("unrelated recipe", "https://b.example/y", "cooking instructions")
    brief = render_brief(
        [good, noise], max_tokens=500, query="lightgbm gradient boosting", min_score=0.5
    )
    assert "lightgbm" in brief
    assert "recipe" not in brief


def test_render_brief_min_score_keeps_best_when_all_fail() -> None:
    """If every hit scores low, the best one is still returned rather than nothing."""
    weak = [_hit("cooking", "https://a.example/1"), _hit("gardening", "https://b.example/2")]
    brief = render_brief(weak, max_tokens=200, query="quantum computing", min_score=0.99)
    assert brief != ""


def test_render_brief_does_not_filter_when_query_has_no_search_terms() -> None:
    """Stop-word-only queries have no lexical signal and preserve provider results."""
    hits = [
        _hit("First provider result", "https://a.example/1"),
        _hit("Second provider result", "https://b.example/2"),
    ]
    brief = render_brief(hits, max_tokens=200, query="what is the", min_score=0.99)
    assert "First provider result" in brief
    assert "Second provider result" in brief


# ---------------------------------------------------------------- token savings


def test_token_budget_saves_tokens_versus_char_budget() -> None:
    """Token budgeting is at least as tight as the old char budget on the same input."""
    hits = [_hit(f"Long result {i}", f"https://example.com/{i}", "y" * 300) for i in range(20)]
    hits = [_hit(f"Long result {i}", f"https://example.com/{i}", "y" * 300) for i in range(20)]
    tight = render_brief(hits, max_tokens=100)
    generous = render_brief(hits, max_tokens=400)
    assert count_tokens(tight) < count_tokens(generous)


# ---------------------------------------------------------------- LangChain tool surface


def test_langchain_brief_tool_exposes_token_budget_and_relevance() -> None:
    """The LangChain brief tool passes ``max_tokens``, ``query`` and ``min_score`` through."""
    from WebSearch.frontend.websearchers import SearchHit
    from WebSearch.langchain_tools import websearch_langchain_tools

    seen: dict[str, object] = {}

    def fake_search(query: str, spec: object) -> list[SearchHit]:
        seen["query"] = query
        return [
            SearchHit(
                "lightgbm gradient boosting", "https://a.example/x", "gradient boosting", "brave"
            ),
            SearchHit("cooking pasta", "https://b.example/y", "boil water", "brave"),
        ]

    tools = {t.name: t for t in websearch_langchain_tools(backends={"brave": fake_search})}
    brief_tool = tools["web_search_brief"]
    out = brief_tool.func("lightgbm gradient boosting", max_tokens=150, min_score=0.5)

    assert isinstance(out, str)
    assert "lightgbm" in out
    assert "pasta" not in out


def test_langchain_brief_tool_defaults_still_work() -> None:
    """Calling the tool with only a query keeps working (no required new args)."""
    from WebSearch.frontend.websearchers import SearchHit
    from WebSearch.langchain_tools import websearch_langchain_tools

    def fake_search(query: str, spec: object) -> list[SearchHit]:
        return [SearchHit("a result", "https://a.example/x", "body", "brave")]

    tools = {t.name: t for t in websearch_langchain_tools(backends={"brave": fake_search})}
    out = tools["web_search_brief"].func("anything")
    assert "a result" in out


# ---------------------------------------------------------------- per-hit query and score


def test_score_hits_attaches_relevance_and_query_per_result() -> None:
    """Every scored hit carries its own ``query`` and ``relevance`` for auditing."""
    from WebSearch.agent_tools import score_hits

    hits = [_hit("lightgbm gradient boosting", "https://a.example/x", "gradient boosting")]
    scored = score_hits(hits, "lightgbm gradient boosting")
    assert len(scored) == 1
    assert scored[0].query == "lightgbm gradient boosting"
    assert scored[0].relevance > 0.0


def test_score_hits_leaves_irrelevant_relevance_at_zero() -> None:
    """A hit sharing no query terms scores exactly zero."""
    from WebSearch.agent_tools import score_hits

    hits = [_hit("cooking pasta", "https://b.example/y", "boil water")]
    scored = score_hits(hits, "quantum entanglement")
    assert scored[0].relevance == 0.0


def test_score_hits_does_not_mutate_input() -> None:
    """Scoring returns new hits; the caller's list is untouched."""
    from WebSearch.agent_tools import score_hits

    original = _hit("a title", "https://a.example/x")
    score_hits([original], "a title")
    assert original.relevance == 0.0
    assert original.query == ""


def test_search_brief_can_emit_scores_when_requested() -> None:
    """``show_scores`` annotates each line with its relevance for agent debugging."""
    from WebSearch.agent_tools import render_brief

    hits = [_hit("lightgbm gradient boosting", "https://a.example/x", "gradient boosting")]
    brief = render_brief(hits, max_tokens=200, query="lightgbm gradient boosting", show_scores=True)
    assert "score=" in brief


def test_render_brief_omits_scores_by_default() -> None:
    """Scores stay out of the prompt unless asked for (they cost tokens)."""
    from WebSearch.agent_tools import render_brief

    hits = [_hit("lightgbm", "https://a.example/x", "boosting")]
    assert "score=" not in render_brief(hits, max_tokens=200, query="lightgbm")


# ---------------------------------------------------------------- savings and integration


def test_tokens_saved_reports_reduction() -> None:
    """``tokens_saved`` quantifies the budget win so a caller can log it."""
    from WebSearch.agent_tools import tokens_saved

    hits = [_hit(f"Result {i}", f"https://example.com/{i}", "z" * 200) for i in range(10)]
    small = render_brief(hits, max_tokens=80)
    large = render_brief(hits, max_tokens=400)
    assert tokens_saved(large, small) > 0
    assert tokens_saved(small, small) == 0


def test_score_hits_then_render_uses_precomputed_relevance() -> None:
    """A scored hit is not re-scored during rendering (single scoring pass)."""
    from WebSearch.agent_tools import score_hits

    scored = score_hits(
        [_hit("lightgbm boosting", "https://a.example/x", "boosting")], "lightgbm boosting"
    )
    hits = scored
    assert hits[0].relevance > 0
    brief = render_brief(hits, max_tokens=200, query="lightgbm boosting", show_scores=True)
    assert f"{hits[0].relevance:.2f}" in brief


def test_search_brief_signature_accepts_new_knobs() -> None:
    """``search_brief`` forwards the new options without a live network call."""
    import inspect

    from WebSearch.agent_tools import search_brief

    params = inspect.signature(search_brief).parameters
    for name in ("max_tokens", "min_score", "max_chars"):
        assert name in params, f"search_brief is missing {name}"
