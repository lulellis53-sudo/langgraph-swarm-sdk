"""Hybrid retrieval: dense vectors + BM25 keywords, merged with reciprocal rank fusion."""

from __future__ import annotations

import math
import re
from collections import Counter

import numpy as np
from pydantic import BaseModel, Field

from swarm_sdk.decorators import Static, wrapper
from swarm_sdk.memory.base import MemoryHit, MemoryStore

_TOKEN_RE = re.compile(r"[a-z0-9]+")


class HybridSearchConfig(BaseModel):
    """Weights and limits for hybrid dense + keyword fusion."""

    enabled: bool = True
    dense_weight: float = Field(default=1.0, ge=0)
    keyword_weight: float = Field(default=1.0, ge=0)
    rrf_k: int = Field(default=60, ge=1)
    final_k: int = Field(default=10, ge=1)


class HybridRetriever:
    """BM25 + dense RRF over memory store candidates."""

    @Static
    @wrapper
    def tokenize(text: str) -> list[str]:
        """Lowercase alphanumeric tokens for BM25 and FTS helpers.

        Args:
            text: Raw query or document text.

        Returns:
            List of token strings.
        """
        return _TOKEN_RE.findall(text.lower())

    @Static
    @wrapper
    def bm25_scores(
        query: str,
        corpus: list[str],
        *,
        k1: float = 1.2,
        b: float = 0.75,
    ) -> list[float]:
        """Score each corpus row with BM25 (in-memory, no index).

        Args:
            query: Search query.
            corpus: Document strings aligned with dense hit order.
            k1: BM25 term-frequency saturation.
            b: BM25 length normalization.

        Returns:
            One score per corpus row.
        """
        docs = [HybridRetriever.tokenize(d) for d in corpus]
        q_terms = Counter(HybridRetriever.tokenize(query))
        if not docs or not q_terms:
            return [0.0] * len(corpus)
        avgdl = sum(len(d) for d in docs) / len(docs)
        n_docs = len(docs)
        df: Counter[str] = Counter()
        for doc in docs:
            df.update(set(doc))
        scores: list[float] = []
        for doc in docs:
            tf = Counter(doc)
            score = 0.0
            for term, q_count in q_terms.items():
                if q_count == 0 or term not in tf:
                    continue
                idf = math.log(1 + (n_docs - df[term] + 0.5) / (df[term] + 0.5))
                denom = tf[term] + k1 * (1 - b + b * len(doc) / avgdl)
                score += idf * tf[term] * (k1 + 1) / denom
            scores.append(score)
        return scores

    @Static
    @wrapper
    def rrf_merge(rankings: list[list[int]], *, k: int = 60) -> list[int]:
        """Reciprocal rank fusion over index rankings.

        Args:
            rankings: Per-signal orderings of candidate indices.
            k: RRF constant (default 60).

        Returns:
            Candidate indices sorted by fused score (best first).
        """
        fused: dict[int, float] = {}
        for ranking in rankings:
            for rank, idx in enumerate(ranking):
                fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + rank + 1)
        return sorted(fused, key=lambda i: fused[i], reverse=True)

    @Static
    def search(
        query: str,
        store: MemoryStore,
        query_vector: np.ndarray,
        *,
        retrieve_k: int,
        config: HybridSearchConfig | None = None,
    ) -> list[MemoryHit]:
        """Dense + BM25 hybrid over store candidates, fused with RRF.

        Args:
            query: Keyword query string.
            store: Vector memory backend.
            query_vector: Embedding for dense ``store.search``.
            retrieve_k: Initial dense candidate count.
            config: Hybrid weights; defaults to enabled config.

        Returns:
            Fused hits up to ``config.final_k``.
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
            kw_scores = HybridRetriever.bm25_scores(query, corpus)
            kw_order = sorted(range(len(corpus)), key=lambda i: kw_scores[i], reverse=True)
            rankings.append(kw_order)
            weights.append(cfg.keyword_weight)

        fused: dict[int, float] = {}
        for ranking, weight in zip(rankings, weights):
            for rank, idx in enumerate(ranking):
                fused[idx] = fused.get(idx, 0.0) + weight / (cfg.rrf_k + rank + 1)
        order = sorted(fused, key=lambda i: fused[i], reverse=True)[: cfg.final_k]

        return [MemoryHit(id=hits[i].id, text=hits[i].text, score=fused[i]) for i in order]


def tokenize(text: str) -> list[str]:
    """See :meth:`HybridRetriever.tokenize`."""
    return HybridRetriever.tokenize(text)


def rrf_merge(rankings: list[list[int]], *, k: int = 60) -> list[int]:
    """See :meth:`HybridRetriever.rrf_merge`."""
    return HybridRetriever.rrf_merge(rankings, k=k)


def hybrid_search(
    query: str,
    store: MemoryStore,
    query_vector: np.ndarray,
    *,
    retrieve_k: int,
    config: HybridSearchConfig | None = None,
) -> list[MemoryHit]:
    """See :meth:`HybridRetriever.search`."""
    return HybridRetriever.search(
        query,
        store,
        query_vector,
        retrieve_k=retrieve_k,
        config=config,
    )


__all__ = ["HybridRetriever", "HybridSearchConfig", "hybrid_search", "rrf_merge", "tokenize"]
