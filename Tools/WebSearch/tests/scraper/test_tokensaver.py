"""Tests for the token saver and the benchmark harness."""

from __future__ import annotations

import pytest
from WebSearch.scraper.benchmark import bench_dedupe_quality, bench_pack_hits, make_synthetic_hits
from WebSearch.scraper.tokensaver import (
    PackResult,
    TokenBudgetExceeded,
    estimate_tokens,
    pack_hits,
    savings_report,
)


def _hit(url: str, snippet: str, score: float = 0.0) -> dict[str, object]:
    return {"url": url, "snippet": snippet, "score": score}


def test_estimate_tokens_is_positive_and_scaled() -> None:
    assert estimate_tokens("") == 0
    short = estimate_tokens("hello")
    long = estimate_tokens("hello world " * 80)
    assert short > 0
    assert long > short


def test_pack_respects_budget_and_keeps_best_scores() -> None:
    # Distinct vocabularies so nothing is a near-duplicate; only the budget cuts.
    hits = [
        _hit("u1", "alpha bravo charlie delta " * 20, score=0.9),
        _hit("u2", "echo foxtrot golf hotel " * 20, score=0.8),
        _hit("u3", "india juliet kilo lima " * 20, score=0.7),
        _hit("u4", "mike november oscar papa " * 20, score=0.6),
    ]
    t1 = estimate_tokens(str(hits[0]["snippet"]))
    t2 = estimate_tokens(str(hits[1]["snippet"]))
    t3 = estimate_tokens(str(hits[2]["snippet"]))
    budget = t1 + t2 + max(1, t3 // 2)
    result = pack_hits(hits, budget_tokens=budget)
    assert isinstance(result, PackResult)
    assert [hit["url"] for hit in result.kept] == ["u1", "u2"]
    assert result.kept[0]["_rank"] == 1
    assert result.tokens_used <= budget
    assert len(result.dropped) == 2
    assert all(d["_drop_reason"] == "budget" for d in result.dropped)


def test_pack_dedupes_urls_and_near_duplicates() -> None:
    base = "rtx 5090 preco oferta brasil loja oficial entrega rapida hoje"
    hits = [
        _hit("a", base, score=0.9),
        _hit("a", base, score=0.95),  # duplicate url, higher score, seen later
        _hit("b", base + " hoje rapida", score=0.8),  # same words: near-duplicate
        _hit("c", "completamente diferente assunto receita de bolo", score=0.7),
    ]
    result = pack_hits(hits, budget_tokens=10_000)
    assert [hit["url"] for hit in result.kept] == ["a", "c"]
    reasons = sorted(d["_drop_reason"] for d in result.dropped)
    assert reasons == ["duplicate_url", "near_duplicate"]
    assert result.duplicates_dropped == 2


def test_pack_zero_budget_reserves_reject() -> None:
    with pytest.raises(TokenBudgetExceeded, match="reserve_tokens"):
        pack_hits([_hit("u", "text")], budget_tokens=10, reserve_tokens=10)


def test_pack_oversized_single_hit_is_a_config_error() -> None:
    with pytest.raises(TokenBudgetExceeded, match="single hit"):
        pack_hits([_hit("u", "word " * 5000)], budget_tokens=100)


def test_pack_missing_scores_keep_stable_order() -> None:
    hits = [_hit("u1", "alpha"), _hit("u2", "beta")]
    result = pack_hits(hits, budget_tokens=1000)
    assert [hit["url"] for hit in result.kept] == ["u1", "u2"]


def test_savings_report_mentions_counts_and_duplicates() -> None:
    hits = [_hit("a", "texto um"), _hit("a", "texto um copia")]
    result = pack_hits(hits, budget_tokens=1000)
    report = savings_report(result, len(hits))
    assert "kept 1/2" in report
    assert "1 duplicates" in report


def test_pack_min_score_drops_off_target() -> None:
    hits = [
        _hit("u1", "langgraph orchestration agents", score=0.9),
        _hit("u2", "banana bread recipe walnuts", score=0.1),
    ]
    result = pack_hits(hits, budget_tokens=1000, min_score=0.3)
    assert [hit["url"] for hit in result.kept] == ["u1"]
    assert result.dropped[0]["_drop_reason"] == "min_score"


def test_pack_on_oversized_drop() -> None:
    result = pack_hits(
        [_hit("u", "word " * 5000)],
        budget_tokens=100,
        on_oversized="drop",
    )
    assert result.kept == []
    assert result.dropped[0]["_drop_reason"] == "too_large"


def test_synthetic_benchmark_helpers() -> None:
    hits = make_synthetic_hits(50, seed=3)
    assert len(hits) == 50
    assert all(h["url"] and h["snippet"] for h in hits)
    pack = bench_pack_hits(count=100)
    assert pack.seconds >= 0.0
    quality = bench_dedupe_quality(count=100)
    assert "recall" in quality.extra
