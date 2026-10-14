"""Core factories: pick the embedder, reranker and vector store the settings select."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from swarm_sdk.config.settings import Settings
from swarm_sdk.memory.base import MemoryStore
from swarm_sdk.memory.sqlite_vec import SqliteVecStore
from swarm_sdk.retrieval.embeddings import (
    Embedder,
    FastEmbedder,
    HashEmbedder,
    LlamaCppEmbedder,
    LlamaServerEmbedder,
)
from swarm_sdk.retrieval.rerank import FastEmbedReranker, KeywordReranker, Reranker

if TYPE_CHECKING:
    pass


def _fastembed_available() -> bool:
    """Return whether the optional ``fastembed`` package is importable."""
    try:
        importlib.import_module("fastembed")
    except ImportError:
        return False
    return True


def default_embedder(settings: Settings) -> Embedder:
    """Build the embedder ``embed_backend`` selects (llama-cpp, hash, or FastEmbed)."""
    batch = settings.embed_batch_size
    if settings.embed_backend == "llama-cpp":
        model_path = settings.llama_embed_model or settings.embed_model
        return LlamaCppEmbedder(
            model_path,
            settings.embed_dim,
            batch,
            n_ctx=settings.llama_n_ctx,
            n_gpu_layers=settings.llama_gpu_layers,
            n_batch=settings.llama_n_batch,
        )
    if settings.embed_backend == "llama-server":
        return LlamaServerEmbedder(
            settings.llama_server_url,
            model=settings.embed_model,
            dim=settings.embed_dim,
            batch_size=settings.llama_n_batch,
        )
    if settings.embed_backend == "hash" or not _fastembed_available():
        return HashEmbedder(settings.embed_dim, batch, settings.embed_model)
    return FastEmbedder(settings.embed_model, settings.embed_dim, batch)


def default_reranker(settings: Settings) -> Reranker:
    """Build the reranker; keyword stand-in when FastEmbed is unavailable."""
    if not _fastembed_available():
        return KeywordReranker()
    return FastEmbedReranker(settings.rerank_model)


def open_store(settings: Settings) -> MemoryStore:
    """Open the vector memory store ``memory_backend`` selects (sqlite-vec default)."""
    if settings.memory_backend == "faiss":
        from swarm_sdk.memory.faiss_store import FaissStore

        return FaissStore(settings.embed_dim, gpu=settings.vector_gpu)
    if settings.memory_backend == "qdrant":
        from swarm_sdk.memory.qdrant_store import QdrantStore

        return QdrantStore(
            settings.memory_path,
            settings.embed_dim,
            quantization=settings.vector_quantization,
        )
    if settings.memory_backend == "opencl":
        from swarm_sdk.memory.opencl_store import OpenClVecStore

        return OpenClVecStore(settings.embed_dim, quantize=settings.opencl_quantize)
    if settings.memory_backend == "mem0":
        from swarm_sdk.memory.mem0_store import Mem0Store

        return Mem0Store.from_settings(settings)
    return SqliteVecStore(settings.memory_path, settings.embed_dim)
