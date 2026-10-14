"""Production-Grade Comprehensive Benchmark Suite for LangGraphSwarm SDK Core Modules.

Measures latency distribution (min/max/mean/P95), throughput (OPS/sec), token compression efficiency,
and RAM memory allocations across core SDK components:
1. RAG Ingestion Pipeline
2. Hybrid Search Reciprocal Rank Fusion (RRF + BM25)
3. Mem0 Async Memory Store & Recall
4. SqliteVec Vector Store Query & Top-K Retrieval
5. Model Selection & Fallback Routing
6. Zstd Zero-Copy State Compression
"""

from __future__ import annotations

import asyncio
import os
import resource
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from swarm_sdk.core.compression import ZstdStateCompressor
from swarm_sdk.memory.mem0_store import Mem0Store
from swarm_sdk.memory.sqlite_vec import SqliteVecStore
from swarm_sdk.models.selection import ModelRoute, ModelSelectConfig, ModelSelector
from swarm_sdk.retrieval.hybrid import HybridSearchConfig, hybrid_search
from swarm_sdk.retrieval.rag_ingest import DocumentChunk, RAGIngestionPipeline


# ==============================================================================
# Helper Utilities
# ==============================================================================

def _get_rss_mb() -> float:
    """Return current process resident set size (ru_maxrss) in Megabytes."""
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        # macOS returns maxrss in bytes
        return usage / (1024.0 * 1024.0)
    # Linux returns maxrss in kilobytes
    return usage / 1024.0


class _MockMem0Client:
    """Synchronous/Asynchronous Mock Mem0 API client for isolated benchmarking."""

    def __init__(self) -> None:
        self.store: list[dict[str, Any]] = []

    def add(self, messages: Any, **kwargs: Any) -> dict[str, Any]:
        text = messages if isinstance(messages, str) else str(messages)
        user_id = kwargs.get("user_id", "default_user")
        record = {
            "id": f"mem-{len(self.store) + 1}",
            "memory": text,
            "user_id": user_id,
            "metadata": kwargs.get("metadata", {}),
            "score": 0.95,
        }
        self.store.append(record)
        return {"results": [record]}

    def search(self, query: str, **kwargs: Any) -> dict[str, Any]:
        # Return matched memory records sorted by synthetic relevance
        user_id = kwargs.get("user_id")
        limit = kwargs.get("limit", 5)
        matched = [
            m for m in self.store if user_id is None or m.get("user_id") == user_id
        ]
        return {"results": matched[:limit]}


# ==============================================================================
# 1. RAG Ingestion Benchmark
# ==============================================================================

@pytest.mark.benchmark(group="rag_ingest")
def test_benchmark_rag_ingest(benchmark: Any, tmp_path: Path) -> None:
    """Benchmark RAG Markdown ingestion & indexing throughput, latency, and memory."""
    # Generate 50 synthetic markdown files with structured headers and code blocks
    doc_paths: list[Path] = []
    for i in range(50):
        p = tmp_path / f"doc_{i}.md"
        content = (
            f"# Core Architecture Module {i}\n\n"
            f"## Section 1: Overview\n"
            f"This is doc {i} detailing system invariants, high performance async routines, "
            f"and vector memory retrieval specs.\n\n"
            f"## Section 2: Technical Specifications\n"
            f"```python\ndef process_chunk_{i}(data: bytes) -> dict:\n    return {{'chunk_id': {i}, 'status': 'ok'}}\n```\n\n"
            f"## Section 3: Performance Bounds\n"
            f"Latencies must remain below 10ms with sub-megabyte RAM overhead for operation {i}.\n"
        )
        p.write_text(content, encoding="utf-8")
        doc_paths.append(p)

    def _run_ingest() -> RAGIngestionPipeline:
        rss_before = _get_rss_mb()
        pipeline = RAGIngestionPipeline(embedding_dim=64, child_size=200)
        pipeline.ingest_files(doc_paths)
        rss_after = _get_rss_mb()
        # Ensure memory delta per run is bounded
        assert (rss_after - rss_before) < 50.0
        return pipeline

    pipeline = benchmark(_run_ingest)
    assert len(pipeline.chunks) >= 50


# ==============================================================================
# 2. Hybrid Search RRF Benchmark
# ==============================================================================

@pytest.mark.benchmark(group="hybrid_search_rrf")
def test_benchmark_hybrid_rrf(benchmark: Any, tmp_path: Path) -> None:
    """Benchmark Hybrid Search RRF (Dense Vector Top-K + BM25 Lexical Ranking)."""
    dim = 64
    store = SqliteVecStore(str(tmp_path / "hybrid_bench.db"), dim=dim)

    # Populate store with 200 documents
    rng = np.random.default_rng(42)
    dummy_vec = np.zeros(dim, dtype=np.float32)
    corpus = [
        f"langgraph swarm sdk vector store query processing engine component {i} latency optimization"
        for i in range(200)
    ]
    for i, text in enumerate(corpus):
        vec = rng.standard_normal(dim).astype(np.float32)
        vec /= np.linalg.norm(vec)
        store.add(text=text, vector=vec)

    query_vec = rng.standard_normal(dim).astype(np.float32)
    query_vec /= np.linalg.norm(query_vec)
    query_text = "swarm sdk vector store latency"

    cfg = HybridSearchConfig(rrf_k=60.0, dense_weight=0.5, keyword_weight=0.5, final_k=10)

    def _run_hybrid() -> list[Any]:
        return hybrid_search(
            query=query_text,
            store=store,
            query_vector=query_vec,
            retrieve_k=20,
            config=cfg,
        )

    hits = benchmark(_run_hybrid)
    assert len(hits) > 0
    store.close()


# ==============================================================================
# 3. Mem0 Async Memory Store Benchmark
# ==============================================================================

@pytest.mark.benchmark(group="mem0_async_memory")
def test_benchmark_mem0_async_store(benchmark: Any) -> None:
    """Benchmark Mem0 Async Memory Store creation, insertion, and text retrieval speed."""
    mock_client = _MockMem0Client()
    mem_store = Mem0Store(client=mock_client)
    dummy_vec = np.zeros(64, dtype=np.float32)

    async def _async_ops() -> list[Any]:
        loop = asyncio.get_running_loop()
        user_id = "user_bench_123"
        # 1. Add memories concurrently via executor to simulate async non-blocking store
        for i in range(10):
            text = f"Agent memory context note {i}: executing system optimization task."
            await loop.run_in_executor(None, mem_store.add, text, dummy_vec)
        # 2. Query recall asynchronously via executor
        hits = await loop.run_in_executor(None, mem_store.search_text, "optimization task", 5)
        return hits

    def _run_async_wrapper() -> list[Any]:
        return asyncio.run(_async_ops())

    hits = benchmark(_run_async_wrapper)
    assert len(hits) > 0


# ==============================================================================
# 4. SqliteVec Vector Store Benchmark
# ==============================================================================

@pytest.mark.benchmark(group="sqlite_vec_store")
def test_benchmark_sqlite_vec_query(benchmark: Any, tmp_path: Path) -> None:
    """Benchmark SqliteVec INT8 scalar quantized vector indexing & top-k query ops."""
    dim = 128
    db_path = tmp_path / "sqlite_vec_bench.db"
    store = SqliteVecStore(str(db_path), dim=dim)

    # Ingest 500 quantized vectors
    rng = np.random.default_rng(123)
    vectors = rng.standard_normal((500, dim)).astype(np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)

    for i in range(500):
        store.add(
            text=f"Benchmark memory item {i} with high density vector",
            vector=vectors[i],
        )

    query_vec = rng.standard_normal(dim).astype(np.float32)
    query_vec /= np.linalg.norm(query_vec)

    def _run_query() -> list[Any]:
        return store.search(query_vec, k=10)

    hits = benchmark(_run_query)
    assert len(hits) == 10
    store.close()


# ==============================================================================
# 5. Model Selection & Fallback Routing Benchmark
# ==============================================================================

@pytest.mark.benchmark(group="model_selection")
def test_benchmark_model_selection(benchmark: Any) -> None:
    """Benchmark ModelSelector candidate route evaluation and think-level dispatch speed."""
    config = ModelSelectConfig(
        default_level="medium",
        routes=[
            ModelRoute(name="openai:gpt-4o-mini", provider="openai", think_levels=("off", "low"), priority=10),
            ModelRoute(name="anthropic:claude-3-5-sonnet", provider="anthropic", think_levels=("low", "medium", "high"), priority=20),
            ModelRoute(name="google:gemini-2.5-pro", provider="google", think_levels=("medium", "high", "xhigh"), priority=30),
        ],
    )
    selector = ModelSelector(config)

    def _run_selection() -> ModelRoute:
        # Route selection evaluation across different think levels
        r1 = selector.select(think_level="low")
        r2 = selector.select(think_level="high")
        r3 = selector.select(think_level="xhigh")
        return r3

    selected = benchmark(_run_selection)
    assert selected.name == "google:gemini-2.5-pro"


# ==============================================================================
# 6. Zstd Zero-Copy State Compression Benchmark
# ==============================================================================

@pytest.mark.benchmark(group="token_state_compression")
def test_benchmark_zstd_token_compression(benchmark: Any) -> None:
    """Benchmark Zstd zero-copy state compression throughput, ratio, and decompression latency."""
    compressor = ZstdStateCompressor(level=3)

    # Generate 100 KB synthetic prompt token state payload
    raw_payload = (
        "system_prompt: You are an autonomous multi-agent swarm orchestrator.\n"
        "context_data: " + ("token_vector_payload_data_chunk_sample_1234567890 " * 2500)
    ).encode("utf-8")

    def _run_compress_decompress() -> tuple[bytes, bytes]:
        compressed = compressor.compress(raw_payload)
        decompressed = compressor.decompress(compressed)
        return compressed, decompressed

    compressed, decompressed = benchmark(_run_compress_decompress)
    assert decompressed == raw_payload
    compression_ratio = len(raw_payload) / len(compressed)
    # Ensure high compression ratio (> 5x for redundant prompt state)
    assert compression_ratio > 5.0
