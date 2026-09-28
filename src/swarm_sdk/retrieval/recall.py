"""Retrieve a wide candidate set, drop duplicates, then keep the reranked top-k."""

from __future__ import annotations

from swarm_sdk.memory.base import MemoryStore
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
