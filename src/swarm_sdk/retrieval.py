"""Retrieve a wide candidate set, drop duplicates, then keep the reranked top-k."""

from __future__ import annotations

from swarm_sdk.decorators import Static
from swarm_sdk.embeddings import Embedder, dedupe_texts
from swarm_sdk.hybrid import HybridRetriever, HybridSearchConfig
from swarm_sdk.memory.base import MemoryStore
from swarm_sdk.rerank import Reranker


class MemoryRecall:
    """End-to-end recall: embed, hybrid search, dedupe, rerank."""

    @Static
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
        """Return top memory snippets for a query.

        Args:
            query: User or router text to match.
            store: Memory backend.
            embedder: Query/passage embedder.
            reranker: Cross-encoder or lexical reranker.
            retrieve_k: Wide candidate pool size.
            rerank_k: Snippets kept after rerank.
            dedup_threshold: Cosine threshold for ``dedupe_texts``.
            hybrid: Hybrid search config from ``swarm.yaml``.
            hybrid_enabled: When False, dense search only.

        Returns:
            Up to ``rerank_k`` deduplicated snippet strings.
        """
        vector = embedder.embed([query], query=True)[0]
        if hybrid_enabled and hybrid is not None and hybrid.enabled:
            hits = HybridRetriever.search(
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
    """See :meth:`MemoryRecall.recall_texts`."""
    return MemoryRecall.recall_texts(
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
