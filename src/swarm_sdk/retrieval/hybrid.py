"""Hybrid retrieval: dense vectors + BM25 keywords, merged with reciprocal rank fusion."""

from __future__ import annotations

import math
from collections import Counter
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from swarm_sdk.memory.base import MemoryHit, MemoryStore
from swarm_sdk.retrieval.text import tokenize

if TYPE_CHECKING:
    import numpy as np


def _bm25_scores(query: str, corpus: list[str], *, k1: float = 1.2, b: float = 0.75) -> list[float]:
    """Lightweight BM25 over the candidate corpus only (no index required)."""
    docs = [tokenize(d) for d in corpus]
    q_terms = Counter(tokenize(query))
    if not docs or not q_terms:
        return [0.0] * len(corpus)
    avgdl = sum(len(d) for d in docs) / len(docs)
    n_docs = len(docs)
    df: Counter[str] = Counter()
    for doc in docs:
        df.update(set(doc))
    scores = []
    for doc in docs:
        tf = Counter(doc)
        score = 0.0
        for term, q_count in q_terms.items():
            if q_count == 0 or term not in tf:
                continue
            idf = math.log(1 + (n_docs - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * tf[term] * (k1 + 1) / (tf[term] + k1 * (1 - b + b * len(doc) / avgdl))
        scores.append(score)
    return scores


def rrf_merge(rankings: list[list[int]], *, k: int = 60) -> list[int]:
    """Reciprocal rank fusion over ranked candidate index lists.

    Args:
        rankings: Each list is candidate indices ordered best-first.
        k: RRF constant (larger → flatter scores).

    Returns:
        Candidate indices sorted by fused score descending.
    """
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return sorted(fused, key=lambda i: fused[i], reverse=True)


class HybridSearchConfig(BaseModel):
    """Weights and caps for dense + keyword hybrid search.

    Attributes:
        enabled: When False, callers should skip hybrid fusion.
        dense_weight: RRF weight for dense vector ranking.
        keyword_weight: RRF weight for BM25 / keyword ranking.
        rrf_k: Reciprocal-rank fusion constant.
        final_k: Max hits returned after fusion.
    """

    enabled: bool = True
    dense_weight: float = Field(default=1.0, ge=0)
    keyword_weight: float = Field(default=1.0, ge=0)
    rrf_k: int = Field(default=60, ge=1)
    final_k: int = Field(default=10, ge=1)


def hybrid_search(
    query: str,
    store: MemoryStore,
    query_vector: np.ndarray,
    *,
    retrieve_k: int,
    config: HybridSearchConfig | None = None,
) -> list[MemoryHit]:
    """Dense + BM25 hybrid over the store's top candidates, fused with RRF.

    Args:
        query: Natural-language query (for BM25 / keyword_search).
        store: Memory store implementing ``search`` (and optionally ``keyword_search``).
        query_vector: Dense query embedding compatible with ``store.search``.
        retrieve_k: Candidate pool size before fusion.
        config: Hybrid weights; defaults to ``HybridSearchConfig()``.

    Returns:
        Up to ``config.final_k`` ``MemoryHit`` rows ordered by fused score.
    """
    cfg = config or HybridSearchConfig()
    hits = list(store.search(query_vector, retrieve_k))
    keyword_search = getattr(store, "keyword_search", None)
    if keyword_search is not None and cfg.keyword_weight > 0:
        for hit in keyword_search(query, retrieve_k):
            if not any(existing.id == hit.id for existing in hits):
                hits.append(hit)
    if not hits:
        return []
    corpus = [hit.text for hit in hits]

    rankings: list[list[int]] = []
    weights: list[float] = []
    if cfg.dense_weight > 0:
        dense_order = sorted(range(len(hits)), key=lambda i: hits[i].score, reverse=True)
        rankings.append(dense_order)
        weights.append(cfg.dense_weight)
    if cfg.keyword_weight > 0:
        kw_scores = _bm25_scores(query, corpus)
        kw_order = sorted(range(len(corpus)), key=lambda i: kw_scores[i], reverse=True)
        rankings.append(kw_order)
        weights.append(cfg.keyword_weight)

    fused: dict[int, float] = {}
    for ranking, weight in zip(rankings, weights):
        for rank, idx in enumerate(ranking):
            fused[idx] = fused.get(idx, 0.0) + weight / (cfg.rrf_k + rank + 1)
    order = sorted(fused, key=lambda i: fused[i], reverse=True)[: cfg.final_k]

    return [MemoryHit(id=hits[i].id, text=hits[i].text, score=fused[i]) for i in order]


__all__ = ["HybridSearchConfig", "hybrid_search", "rrf_merge", "tokenize"]
