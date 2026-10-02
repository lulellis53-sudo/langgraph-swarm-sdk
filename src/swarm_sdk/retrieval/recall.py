"""Retrieve a wide candidate set, drop duplicates, then keep the reranked top-k."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import cast

from swarm_sdk.memory.base import MemoryHit, MemoryStore
from swarm_sdk.retrieval.embeddings import Embedder, dedupe_texts
from swarm_sdk.retrieval.hybrid import HybridSearchConfig, hybrid_search
from swarm_sdk.retrieval.rerank import Reranker


def _candidate_hits(
    query: str,
    store: MemoryStore,
    embedder: Embedder,
    *,
    retrieve_k: int,
    hybrid: HybridSearchConfig | None,
    hybrid_enabled: bool,
) -> list[MemoryHit]:
    """Fetch candidates: store-native text search, hybrid RRF, or dense top-k."""
    search_text = cast(
        Callable[[str, int], Iterable[MemoryHit]] | None,
        getattr(store, "search_text", None),
    )
    if callable(search_text):
        return list(search_text(query, retrieve_k))
    vector = embedder.embed([query], query=True)[0]
    if hybrid_enabled and hybrid is not None and hybrid.enabled:
        # Widen final_k to the candidate budget so the reranker sees everything
        # retrieved; it slices to rerank_k afterwards.
        wide = hybrid.model_copy(update={"final_k": max(retrieve_k, hybrid.final_k)})
        return hybrid_search(query, store, vector, retrieve_k=retrieve_k, config=wide)
    return store.search(vector, retrieve_k)


def recall_hits(
    query: str,
    store: MemoryStore,
    embedder: Embedder,
    reranker: Reranker,
    *,
    retrieve_k: int,
    rerank_k: int,
    dedup_threshold: float,
    hybrid: HybridSearchConfig | None = None,
    hybrid_enabled: bool = True,
) -> list[MemoryHit]:
    """Recall, dedupe, and rerank memory hits for a query.

    Args:
        query: User / router query text.
        store: Vector memory, or a store with ``search_text`` (Mem0).
        embedder: Embedder used for query and passage vectors.
        reranker: Cross-encoder or lexical reranker.
        retrieve_k: Candidate count from dense/hybrid search.
        rerank_k: Max hits returned after reranking.
        dedup_threshold: Cosine similarity threshold for near-duplicate drop.
        hybrid: Optional hybrid search config (dense + BM25 RRF).
        hybrid_enabled: When False, force dense-only search.

    Returns:
        Up to ``rerank_k`` hits, highest relevance first.
    """
    hits = _candidate_hits(
        query,
        store,
        embedder,
        retrieve_k=retrieve_k,
        hybrid=hybrid,
        hybrid_enabled=hybrid_enabled,
    )
    if not hits:
        return []
    texts = [hit.text for hit in hits]
    unique = dedupe_texts(texts, embedder.embed(texts, query=False), dedup_threshold)
    by_text: dict[str, MemoryHit] = {}
    for hit in hits:
        by_text.setdefault(hit.text, hit)
    ranked = reranker.rerank(query, unique)
    return [by_text[text] for text in ranked[:rerank_k] if text in by_text]


def recall_texts(
    query: str,
    store: MemoryStore,
    embedder: Embedder,
    reranker: Reranker,
    *,
    retrieve_k: int,
    rerank_k: int,
    dedup_threshold: float,
    hybrid: HybridSearchConfig | None = None,
    hybrid_enabled: bool = True,
) -> list[str]:
    """Recall, dedupe, and rerank memory texts for a query.

    Thin text-only wrapper over :func:`recall_hits`; see it for parameters.

    Returns:
        Up to ``rerank_k`` passage texts, highest relevance first.
    """
    return [
        hit.text
        for hit in recall_hits(
            query,
            store,
            embedder,
            reranker,
            retrieve_k=retrieve_k,
            rerank_k=rerank_k,
            dedup_threshold=dedup_threshold,
            hybrid=hybrid,
            hybrid_enabled=hybrid_enabled,
        )
    ]


__all__ = ["recall_hits", "recall_texts"]
