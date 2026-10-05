"""Query routing, late-chunk pooling, and CRAG / Self-RAG decisions.

The dense path is the default. A relational query is marked for a graph hop.
Late chunking mean-pools token rows over caller-supplied spans. CRAG turns the
existing confidence gate into proceed, mixed, or web-fallback. Self-RAG turns
that same gate into retrieve, irrelevant, or supported.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from swarm_sdk.retrieval.embeddings import unit
from swarm_sdk.retrieval.gate import Confidence

__all__ = [
    "BGE_DIM",
    "BGE_SMALL_MODEL",
    "CragAction",
    "QueryPath",
    "Reflection",
    "RetrievalPlan",
    "crag_action",
    "plan_retrieval",
    "pool_late_chunks",
    "redis_hnsw_spec",
    "reflect",
    "route_query",
]

#: Dossier embedding model. The runtime default stays MiniLM because this host
#: has no FastEmbed ONNX wheel.
BGE_SMALL_MODEL = "BAAI/bge-small-en-v1.5"
BGE_DIM = 384

_GRAPH_MARKERS = (
    "relationship",
    "relate",
    "between",
    "compare",
    "versus",
    "connected to",
    "multi-hop",
)


class QueryPath(StrEnum):
    """Which retrieval arm the query router selects."""

    DENSE = "dense"
    GRAPH = "graph"


class CragAction(StrEnum):
    """What CRAG does with a confidence bucket."""

    PROCEED = "proceed"
    MIXED = "mixed"
    WEB_FALLBACK = "web_fallback"


class Reflection(StrEnum):
    """Self-RAG reflection for one retrieval result."""

    RETRIEVE = "retrieve"
    IRRELEVANT = "irrelevant"
    SUPPORTED = "supported"


@dataclass(frozen=True, slots=True)
class RetrievalPlan:
    """Router arm plus the corrective and reflection decisions.

    Attributes:
        path: Dense vector search or a graph hop.
        crag: Whether to generate, mix in web results, or leave the corpus.
        reflection: Self-RAG label for the kept chunks.
    """

    path: QueryPath
    crag: CragAction
    reflection: Reflection


def route_query(query: str) -> QueryPath:
    """Send a relational query to the graph arm and everything else to dense search.

    Args:
        query: User text. It is matched, not executed.

    Returns:
        ``QueryPath.GRAPH`` when a relational marker is present.
    """
    text = query.casefold()
    if any(marker in text for marker in _GRAPH_MARKERS):
        return QueryPath.GRAPH
    return QueryPath.DENSE


def crag_action(confidence: Confidence) -> CragAction:
    """Map a confidence bucket to a CRAG action.

    Args:
        confidence: Gate output. High proceeds, low leaves the corpus, ambiguous mixes.
    """
    if confidence is Confidence.HIGH:
        return CragAction.PROCEED
    if confidence is Confidence.LOW:
        return CragAction.WEB_FALLBACK
    return CragAction.MIXED


def reflect(confidence: Confidence, *, kept: int) -> Reflection:
    """Label a result the way Self-RAG labels a retrieval step.

    Args:
        confidence: Gate output.
        kept: How many chunks survived the gate.
    """
    if confidence is Confidence.HIGH and kept > 0:
        return Reflection.SUPPORTED
    if confidence is Confidence.LOW or kept == 0:
        return Reflection.RETRIEVE
    return Reflection.IRRELEVANT


def plan_retrieval(query: str, confidence: Confidence, *, kept: int) -> RetrievalPlan:
    """Combine the query router, CRAG, and Self-RAG for one recall."""
    return RetrievalPlan(
        path=route_query(query),
        crag=crag_action(confidence),
        reflection=reflect(confidence, kept=kept),
    )


def pool_late_chunks(
    token_embeddings: np.ndarray,
    spans: Sequence[tuple[int, int]],
) -> np.ndarray:
    """Mean-pool token rows over each ``[start, end)`` span and L2-normalize.

    Args:
        token_embeddings: One row per token of a document embedded before chunking.
        spans: Token spans. Each end is exclusive and must sit inside the matrix.

    Returns:
        One unit vector per span. An empty span list returns shape ``(0, dim)``.

    Raises:
        ValueError: When the matrix is not 2-D or a span is empty or out of range.
    """
    rows = np.asarray(token_embeddings, dtype=np.float32)
    if rows.ndim != 2:
        raise ValueError("token embeddings must be a 2-d matrix")
    pooled: list[np.ndarray] = []
    limit = rows.shape[0]
    for start, end in spans:
        if start < 0 or end > limit or start >= end:
            raise ValueError("span is outside the token matrix")
        pooled.append(unit(rows[start:end].mean(axis=0)))
    if not pooled:
        return np.zeros((0, rows.shape[1]), dtype=np.float32)
    return np.vstack(pooled)


def redis_hnsw_spec() -> dict[str, object]:
    """RediSearch HNSW fields for 384-d cosine vectors.

    Returns:
        Index name, key prefix, and vector parameters. This does not open Redis.
    """
    return {
        "index": "idx:rag",
        "prefix": "doc:",
        "content_field": "content",
        "vector_field": "embedding",
        "algorithm": "HNSW",
        "type": "FLOAT32",
        "dim": BGE_DIM,
        "distance": "COSINE",
        "model": BGE_SMALL_MODEL,
    }
