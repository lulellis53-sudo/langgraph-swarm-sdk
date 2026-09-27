"""Retrieve a wide candidate set, drop duplicates, then keep the reranked top-k."""

from __future__ import annotations

from swarm_sdk.embeddings import Embedder, dedupe_texts
from swarm_sdk.memory.base import MemoryStore
from swarm_sdk.rerank import Reranker


def recall_texts(
    query: str,
    store: MemoryStore,
    embedder: Embedder,
    reranker: Reranker,
    *,
    retrieve_k: int,
    rerank_k: int,
    dedup_threshold: float,
) -> list[str]:
    vector = embedder.embed([query])[0]
    hits = store.search(vector, retrieve_k)
    if not hits:
        return []
    texts = [hit.text for hit in hits]
    unique = dedupe_texts(texts, embedder.embed(texts), dedup_threshold)
    return reranker.rerank(query, unique)[:rerank_k]
