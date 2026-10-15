"""Scored reranking, the confidence gate and gated recall."""

from __future__ import annotations

from pathlib import Path

import pytest
from benchmark.tests.fakes import sdk_with_router

from swarm_sdk.core.swarm import SwarmSDK
from swarm_sdk.retrieval.gate import Confidence, GateConfig, classify
from swarm_sdk.retrieval.rerank import IdentityReranker, KeywordReranker

CFG = GateConfig(enabled=True, high=0.5, low=0.2)


def test_classify_boundaries() -> None:
    assert classify([0.5, 0.1], CFG) is Confidence.HIGH
    assert classify([0.4999], CFG) is Confidence.AMBIGUOUS
    assert classify([0.2], CFG) is Confidence.AMBIGUOUS
    assert classify([0.1999], CFG) is Confidence.LOW
    assert classify([], CFG) is Confidence.LOW


def test_classify_uses_the_best_score_regardless_of_order() -> None:
    assert classify([0.0, 0.9, 0.1], CFG) is Confidence.HIGH


def test_gate_config_rejects_inverted_thresholds() -> None:
    with pytest.raises(ValueError):
        GateConfig(high=0.2, low=0.5)


def test_keyword_rerank_scored_matches_rerank_order_and_is_normalized() -> None:
    docs = ["alpha beta", "gamma", "alpha beta gamma delta"]
    scored = KeywordReranker().rerank_scored("alpha beta", docs)
    assert [d for d, _ in scored] == KeywordReranker().rerank("alpha beta", docs)
    assert all(0.0 <= s <= 1.0 for _, s in scored)
    assert scored[0][1] == 1.0
    assert KeywordReranker().rerank_scored("", docs)[0][1] == 0.0
    assert KeywordReranker().rerank_scored("x", []) == []


def _seed(sdk: SwarmSDK) -> None:
    for text in ["sqlite vector memory store", "semantic cache expiry", "token budget limit"]:
        sdk.memory.add(text, sdk.embedder.embed([text], query=False)[0])


def test_gate_drops_weak_recall_and_keeps_strong(tmp_path: Path) -> None:
    sdk = sdk_with_router(tmp_path, "{}")
    _seed(sdk)
    sdk.reranker = KeywordReranker()
    sdk.file_config.rag.gate = CFG
    assert sdk.recall("pasta carbonara") == []
    top = sdk.recall("sqlite vector memory store")[0]
    assert top.text == "sqlite vector memory store"


def test_gate_is_inert_without_a_scored_reranker(tmp_path: Path) -> None:
    sdk = sdk_with_router(tmp_path, "{}")
    _seed(sdk)
    sdk.reranker = IdentityReranker()
    off = sdk.recall("pasta carbonara")
    sdk.file_config.rag.gate = CFG
    assert sdk.recall("pasta carbonara") == off  # no scores, so no gating
    assert off != []


def test_gate_disabled_matches_recall_hits(tmp_path: Path) -> None:
    sdk = sdk_with_router(tmp_path, "{}")
    _seed(sdk)
    sdk.reranker = KeywordReranker()
    before = sdk.recall("sqlite")
    sdk.file_config.rag.gate = GateConfig(enabled=False)
    assert sdk.recall("sqlite") == before
