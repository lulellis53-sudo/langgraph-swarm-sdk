"""Retrieval domain: embeddings, search, reranking, and semantic caching."""

from __future__ import annotations

from swarm_sdk.retrieval.cache import SemanticCache
from swarm_sdk.retrieval.embeddings import (
    Embedder,
    EmbeddingServerError,
    FastEmbedder,
    HashEmbedder,
    LlamaCppEmbedder,
    LlamaServerEmbedder,
)
from swarm_sdk.retrieval.gate import Confidence, GateConfig, classify
from swarm_sdk.retrieval.hybrid import HybridSearchConfig, hybrid_search
from swarm_sdk.retrieval.ordering import order_for_prompt, u_shape
from swarm_sdk.retrieval.rag_ingest import (
    DocumentChunk,
    RAGIngestionPipeline,
    RetrievalResult,
)
from swarm_sdk.retrieval.rag_route import (
    BGE_SMALL_MODEL,
    CragAction,
    QueryPath,
    Reflection,
    RetrievalPlan,
    plan_retrieval,
    pool_late_chunks,
    route_query,
)
from swarm_sdk.retrieval.recall import (
    RecallResult,
    recall_hits,
    recall_texts,
    recall_with_confidence,
)
from swarm_sdk.retrieval.rerank import (
    FastEmbedReranker,
    IdentityReranker,
    KeywordReranker,
    Reranker,
)
from swarm_sdk.retrieval.text import tokenize

__all__ = [
    "Confidence",
    "DocumentChunk",
    "Embedder",
    "FastEmbedReranker",
    "FastEmbedder",
    "GateConfig",
    "HashEmbedder",
    "HybridSearchConfig",
    "IdentityReranker",
    "KeywordReranker",
    "LlamaCppEmbedder",
    "LlamaServerEmbedder",
    "EmbeddingServerError",
    "BGE_SMALL_MODEL",
    "CragAction",
    "QueryPath",
    "RAGIngestionPipeline",
    "RecallResult",
    "Reflection",
    "RetrievalPlan",
    "Reranker",
    "RetrievalResult",
    "SemanticCache",
    "classify",
    "hybrid_search",
    "order_for_prompt",
    "plan_retrieval",
    "pool_late_chunks",
    "recall_hits",
    "route_query",
    "recall_texts",
    "recall_with_confidence",
    "tokenize",
    "u_shape",
]
