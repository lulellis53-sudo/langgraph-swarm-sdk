"""Tests for swarm_sdk.math symbolic and numerical helpers."""

from __future__ import annotations

import math

import pytest

from swarm_sdk import math as sm


def test_bm25_idf_positive_and_finite() -> None:
    for n_docs in (1, 10, 100):
        for df in range(1, n_docs + 1):
            value = sm.bm25_idf(n_docs, df)
            assert 0.0 < value < math.inf


def test_bm25_score_matches_canonical_formula() -> None:
    query = ["the", "quick", "brown"]
    doc = ["the", "quick", "quick", "brown", "fox"]
    n_docs = 10
    df_map = {"the": 5, "quick": 3, "brown": 2}
    score = sm.bm25_score(query, doc, n_docs=n_docs, df_map=df_map, k1=1.2, b=0.75)

    expected = 0.0
    avgdl = len(doc)
    for term in set(query):
        if term not in doc:
            continue
        tf = doc.count(term)
        idf = math.log(1 + (n_docs - df_map[term] + 0.5) / (df_map[term] + 0.5))
        denom = tf + 1.2 * (1 - 0.75 + 0.75 * len(doc) / avgdl)
        expected += idf * tf * 2.2 / denom
    assert score == pytest.approx(expected, rel=1e-9)


def test_rrf_score_decreases_with_rank() -> None:
    scores = [sm.rrf_score(r) for r in range(10)]
    assert all(scores[i] > scores[i + 1] for i in range(len(scores) - 1))
    assert sm.rrf_score(0, k=60) == pytest.approx(1 / 61)


def test_softmax_sums_to_one_and_shift_invariant() -> None:
    scores = [1.0, 2.0, 3.0]
    p = sm.softmax_scores(scores)
    assert sum(p) == pytest.approx(1.0, abs=1e-9)
    shifted = sm.softmax_scores([s + 100.0 for s in scores])
    for a, b in zip(p, shifted, strict=True):
        assert a == pytest.approx(b, rel=1e-9)


def test_int8_scale_handles_zero_and_positive_peak() -> None:
    assert sm.int8_scale(0.0) == 1.0
    assert sm.int8_scale(127.0) == 1.0
    assert sm.int8_scale(254.0) == 2.0


def test_int8_quantize_rounds_and_clips() -> None:
    scale = 1.0
    assert sm.int8_quantize(0.4, scale) == 0
    assert sm.int8_quantize(0.6, scale) == 1
    assert sm.int8_quantize(-0.6, scale) == -1
    assert sm.int8_quantize(200.0, scale) == 127
    assert sm.int8_quantize(-200.0, scale) == -127


def test_binary_cosine_estimate_maps_endpoints() -> None:
    dim = 128
    assert sm.binary_cosine_estimate(0, dim) == pytest.approx(1.0)
    assert sm.binary_cosine_estimate(dim, dim) == pytest.approx(-1.0)
    assert sm.binary_cosine_estimate(dim // 2, dim) == pytest.approx(0.0, abs=1e-9)


def test_binary_score_to_cosine_is_inverse() -> None:
    dim = 64
    for hamming in (0, dim // 4, dim // 2, dim):
        score = dim - hamming
        cosine = sm.binary_score_to_cosine(score, dim)
        assert cosine == pytest.approx(sm.binary_cosine_estimate(hamming, dim))


def test_cosine_similarity_matches_numpy_norm() -> None:
    u = [1.0, 0.0, 0.0]
    v = [0.0, 1.0, 0.0]
    assert sm.cosine_similarity(u, v) == pytest.approx(0.0, abs=1e-9)
    assert sm.cosine_similarity(u, u) == pytest.approx(1.0)
    assert sm.cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_l2_norm() -> None:
    assert sm.l2_norm([3.0, 4.0]) == pytest.approx(5.0)
    assert sm.l2_norm([0.0, 0.0]) == 0.0


def test_symbolic_bm25_is_equation() -> None:
    eq = sm.symbolic_bm25()
    assert eq.func.__name__ == "Equality"
    assert "BM25" in str(eq.lhs)


def test_symbolic_rrf_is_equation() -> None:
    eq = sm.symbolic_rrf()
    assert eq.func.__name__ == "Equality"


def test_symbolic_softmax_is_equation() -> None:
    eq = sm.symbolic_softmax()
    assert eq.func.__name__ == "Equality"


def test_symbolic_cosine_is_equation() -> None:
    eq = sm.symbolic_cosine()
    assert eq.func.__name__ == "Equality"
