r"""Hybrid retrieval: dense vectors + BM25 keywords, merged with reciprocal rank fusion.

BM25 scores keyword matches and RRF merges rankings from different sources without
requiring score calibration.

Key formulas:

.. math::
    \operatorname{idf}(t) = \ln\!\left(
        1 + \frac{N - \operatorname{df}(t) + 0.5}{\operatorname{df}(t) + 0.5}
    \right)

.. math::
    \operatorname{BM25}(D, Q) = \sum_{t \in Q}
        \operatorname{idf}(t) \cdot
        \frac{\operatorname{tf}(t, D) \cdot (k_1 + 1)}
             {\operatorname{tf}(t, D) + k_1 \cdot
              \left(1 - b + b \cdot \frac{|D|}{\operatorname{avgdl}}\right)}

.. math::
    \operatorname{RRF}(r) = \frac{1}{k + r + 1}

where ``r`` is a 0-based rank.
"""

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
    r"""Lightweight BM25 over the candidate corpus only (no index required).

    Computes

    .. math::
        \operatorname{score}(D) = \sum_{t \in Q \cap D}
            \operatorname{idf}(t) \cdot
            \frac{\operatorname{tf}(t, D) \cdot (k_1 + 1)}
                 {\operatorname{tf}(t, D) + k_1 \cdot
                  \left(1 - b + b \cdot \frac{|D|}{\operatorname{avgdl}}\right)}

    with ``idf(t)`` defined in the module docstring.
    """
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
    r"""Reciprocal rank fusion over ranked candidate index lists.

    Fused score for candidate ``i``:

    .. math::
        \operatorname{score}(i) = \sum_{R \in \text{rankings}}
            \frac{1}{k + \operatorname{rank}_R(i) + 1}

    where :math:`\operatorname{rank}_R(i)` is the 0-based position of ``i`` in
    ranking ``R`` (omitted if absent).

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
    r"""Weights and caps for dense + keyword hybrid search.

    The final fused score for a candidate is the weighted sum of its RRF
    contributions from each ranking source:

    .. math::
        \operatorname{fused}(i) = \sum_s w_s \cdot
            \frac{1}{k + \operatorname{rank}_s(i) + 1}

    Attributes:
        enabled: When False, callers should skip hybrid fusion.
        dense_weight: RRF weight :math:`w_{\text{dense}}` for dense vector ranking.
        keyword_weight: RRF weight :math:`w_{\text{keyword}}` for BM25 / keyword ranking.
        rrf_k: Reciprocal-rank fusion constant :math:`k`.
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
    r"""Dense + BM25 hybrid over the store's top candidates, fused with RRF.

    Combines a dense vector ranking with a BM25 keyword ranking using weighted
    reciprocal rank fusion:

    .. math::
        \operatorname{fused}(i) = w_{\text{dense}} \cdot \operatorname{RRF}(i; R_{\text{dense}})
                                + w_{\text{keyword}} \cdot \operatorname{RRF}(i; R_{\text{keyword}})

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
