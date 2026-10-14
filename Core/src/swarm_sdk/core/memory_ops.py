"""Memory recall and persistence operations for the swarm SDK."""

from __future__ import annotations

from typing import TYPE_CHECKING

from swarm_sdk.memory.base import MemoryHit
from swarm_sdk.retrieval.ordering import order_for_prompt
from swarm_sdk.retrieval.recall import recall_hits, recall_with_confidence

if TYPE_CHECKING:
    from swarm_sdk.core.swarm import SwarmSDK


class MemoryOps:
    """Hybrid-retrieval recall and Q/A memory persistence, backed by the SDK stores."""

    def __init__(self, sdk: SwarmSDK) -> None:
        self._sdk = sdk

    def recall(self, query: str, top_k: int | None = None) -> list[MemoryHit]:
        """Hybrid-retrieval memory hits: recall, dedupe, rerank, capped at ``top_k``."""
        sdk = self._sdk
        retrieve_k = max(top_k or sdk.settings.rerank_k, sdk.settings.retrieve_k)
        rerank_k = top_k or sdk.settings.rerank_k
        gate = sdk.file_config.rag.gate
        if gate.enabled:
            return recall_with_confidence(
                query,
                sdk.memory,
                sdk.embedder,
                sdk.reranker,
                retrieve_k=retrieve_k,
                rerank_k=rerank_k,
                dedup_threshold=sdk.settings.dedup_threshold,
                gate=gate,
                hybrid=sdk.file_config.hybrid_search,
                hybrid_enabled=sdk.settings.hybrid_enabled,
            ).hits
        return recall_hits(
            query,
            sdk.memory,
            sdk.embedder,
            sdk.reranker,
            retrieve_k=retrieve_k,
            rerank_k=rerank_k,
            dedup_threshold=sdk.settings.dedup_threshold,
            hybrid=sdk.file_config.hybrid_search,
            hybrid_enabled=sdk.settings.hybrid_enabled,
        )

    def recall_for_prompt(self, text: str) -> list[str]:
        """Recall memories for ``text``, ordered for the prompt (U-shape when enabled)."""
        texts = [hit.text for hit in self.recall(text)]
        return order_for_prompt(texts, enabled=self._sdk.file_config.rag.u_shape_order)

    def remember(self, question: str, answer: str) -> None:
        """Persist a truncated question/answer pair as one embedded memory record."""
        record = f"Q: {question[:200]}\nA: {answer[:400]}"
        vector = self._sdk.embedder.embed([record], query=False)[0]
        self._sdk.memory.add(record, vector)


__all__ = ["MemoryOps"]
