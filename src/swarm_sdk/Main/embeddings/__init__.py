"""Re-export of ``swarm_sdk.retrieval.embeddings``. Prefer importing from ``swarm_sdk``."""

from __future__ import annotations

from swarm_sdk.retrieval.embeddings import (
    Embedder,
    FastEmbedder,
    HashEmbedder,
    LlamaCppEmbedder,
    cosine,
    dedupe_texts,
    unit,
)

__all__ = [
    "Embedder",
    "FastEmbedder",
    "HashEmbedder",
    "LlamaCppEmbedder",
    "cosine",
    "dedupe_texts",
    "unit",
]
