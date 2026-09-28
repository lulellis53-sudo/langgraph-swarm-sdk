"""Retrieve a wide candidate set, drop duplicates, then keep the reranked top-k."""

from __future__ import annotations

from swarm_sdk.memory.base import MemoryHit, MemoryStore
from swarm_sdk.retrieval.embeddings import Embedder, dedupe_texts
from swarm_sdk.retrieval.hybrid import HybridSearchConfig, hybrid_search
from swarm_sdk.retrieval.rerank import Reranker


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

    Args:
        query: User / router query text.
        store: Vector memory, or a store with ``search_text`` (Mem0).
        embedder: Embedder used for query and passage vectors.
        reranker: Cross-encoder or lexical reranker.
        retrieve_k: Candidate count from dense/hybrid search.
        rerank_k: Max texts returned after reranking.
        dedup_threshold: Cosine similarity threshold for near-duplicate drop.
        hybrid: Optional hybrid search config (dense + BM25 RRF).
        hybrid_enabled: When False, force dense-only search.

    Returns:
        Up to ``rerank_k`` passage texts, highest relevance first.
    """
    search_text = getattr(store, "search_text", None)
    if callable(search_text):
        hits = list(search_text(query, retrieve_k))
        texts = [hit.text for hit in hits if isinstance(hit, MemoryHit)]
    else:
        vector = embedder.embed([query], query=True)[0]
        if hybrid_enabled and hybrid is not None and hybrid.enabled:
            hits = hybrid_search(
                query,
                store,
                vector,
                retrieve_k=retrieve_k,
                config=hybrid,
            )
            texts = [hit.text for hit in hits]
        else:
            hits = store.search(vector, retrieve_k)
            if not hits:
                return []
            texts = [hit.text for hit in hits]

    if not texts:
        return []
    unique = dedupe_texts(texts, embedder.embed(texts, query=False), dedup_threshold)
    return reranker.rerank(query, unique)[:rerank_k]


__all__ = ["recall_texts"]
