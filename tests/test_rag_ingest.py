"""Comprehensive tests for RAG ingestion pipeline and contextual chunking."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import numpy as np
import pytest

from swarm_sdk.retrieval.rag_ingest import (
    DocumentChunk,
    RAGIngestionPipeline,
    RetrievalResult,
    _NumpyVectorStore,
)


class MockEmbedder:
    """Deterministic mock embedder for tests."""

    def __init__(self, dim: int = 64) -> None:
        self.dim = dim

    def embed(self, texts: list[str], *, query: bool = False) -> np.ndarray:
        # Create deterministic orthogonal-like or distinct vectors based on text content
        rows: list[np.ndarray] = []
        for text in texts:
            vec = np.zeros(self.dim, dtype=np.float32)
            # Encode character codes into the vector
            for i, ch in enumerate(text.lower()[: self.dim]):
                vec[i % self.dim] += ord(ch)
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            rows.append(vec)
        return np.vstack(rows) if rows else np.zeros((0, self.dim), dtype=np.float32)


# ==============================================================================
# 1. Pydantic Schema Tests
# ==============================================================================


def test_document_chunk_schema() -> None:
    chunk = DocumentChunk(
        chunk_id="doc1:0",
        source_file="doc1.md",
        header_context="Title > Section",
        content="This is section content.",
        full_text="Title > Section\nThis is section content.",
    )
    assert chunk.chunk_id == "doc1:0"
    assert chunk.source_file == "doc1.md"
    assert chunk.header_context == "Title > Section"
    assert chunk.content == "This is section content."
    assert chunk.full_text == "Title > Section\nThis is section content."
    assert chunk.metadata == {}

    # Serialization round-trip
    dumped = chunk.model_dump()
    loaded = DocumentChunk.model_validate(dumped)
    assert loaded == chunk


def test_retrieval_result_schema() -> None:
    chunk = DocumentChunk(
        chunk_id="test_0",
        source_file="test.md",
        header_context="",
        content="hello",
        full_text="hello",
    )
    result = RetrievalResult(chunk=chunk, score=0.95)
    assert result.chunk == chunk
    assert pytest.approx(result.score, rel=1e-4) == 0.95


# ==============================================================================
# 2. Contextual Markdown Chunking Tests
# ==============================================================================


def test_chunk_markdown_single_header() -> None:
    pipeline = RAGIngestionPipeline(embedding_dim=64)
    md = """# Swarm Framework
Swarm is a lightweight multi-agent orchestration framework.
"""
    chunks = pipeline.chunk_markdown(md, source_file="intro.md")
    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.source_file == "intro.md"
    assert chunk.header_context == "Swarm Framework"
    assert chunk.content == "Swarm is a lightweight multi-agent orchestration framework."
    assert chunk.full_text == "Swarm Framework\nSwarm is a lightweight multi-agent orchestration framework."
    assert chunk.metadata["headers"] == ["Swarm Framework"]


def test_chunk_markdown_nested_hierarchy() -> None:
    pipeline = RAGIngestionPipeline(embedding_dim=64)
    md = """# Architecture
High-level overview.

## Memory Subsystem
Memory handles retrieval and storage.

### Vector Storage
FAISS and SQLite Vec backends.

## Dispatcher
Dispatcher schedules tasks.
"""
    chunks = pipeline.chunk_markdown(md, source_file="arch.md")
    assert len(chunks) == 4

    # Chunk 0: Architecture
    assert chunks[0].header_context == "Architecture"
    assert chunks[0].content == "High-level overview."
    assert chunks[0].full_text == "Architecture\nHigh-level overview."

    # Chunk 1: Memory Subsystem
    assert chunks[1].header_context == "Architecture > Memory Subsystem"
    assert chunks[1].content == "Memory handles retrieval and storage."

    # Chunk 2: Vector Storage
    assert chunks[2].header_context == "Architecture > Memory Subsystem > Vector Storage"
    assert chunks[2].content == "FAISS and SQLite Vec backends."

    # Chunk 3: Dispatcher (popped back to level 2)
    assert chunks[3].header_context == "Architecture > Dispatcher"
    assert chunks[3].content == "Dispatcher schedules tasks."


def test_chunk_markdown_preamble_and_empty_headers() -> None:
    pipeline = RAGIngestionPipeline(embedding_dim=64)
    md = """This is a preamble before any header.

# Empty Parent Header
## First Child
Child content here.
"""
    chunks = pipeline.chunk_markdown(md, source_file="preamble.md")
    assert len(chunks) == 2

    # Chunk 0: Preamble
    assert chunks[0].header_context == ""
    assert chunks[0].content == "This is a preamble before any header."
    assert chunks[0].full_text == "This is a preamble before any header."

    # Chunk 1: First Child (inherited Empty Parent Header into hierarchy)
    assert chunks[1].header_context == "Empty Parent Header > First Child"
    assert chunks[1].content == "Child content here."


def test_chunk_markdown_code_block_with_comments() -> None:
    pipeline = RAGIngestionPipeline(embedding_dim=64)
    md = """# Python Guide
Here is some code:

```python
# This is a python comment, not a markdown header
def hello():
    # Another comment
    return 42
```
And after the code block.
"""
    chunks = pipeline.chunk_markdown(md, source_file="code.md")
    assert len(chunks) == 1
    assert chunks[0].header_context == "Python Guide"
    assert "def hello():" in chunks[0].content
    assert "# This is a python comment" in chunks[0].content


def test_chunk_markdown_no_headers() -> None:
    pipeline = RAGIngestionPipeline(embedding_dim=64)
    text = "Just plain text without any markdown headers.\nLine 2 of plain text."
    chunks = pipeline.chunk_markdown(text, source_file="plain.txt")
    assert len(chunks) == 1
    assert chunks[0].header_context == ""
    assert chunks[0].content == text.strip()
    assert chunks[0].full_text == text.strip()


def test_chunk_markdown_large_section_splitting() -> None:
    pipeline = RAGIngestionPipeline(embedding_dim=64)
    p1 = "Paragraph 1 is detailed description of topic A. " * 10
    p2 = "Paragraph 2 is detailed description of topic B. " * 10
    md = f"# Topic\n\n{p1}\n\n{p2}"

    # With small max_chunk_size, should split paragraphs while preserving header_context
    chunks = pipeline.chunk_markdown(md, source_file="topic.md", max_chunk_size=200)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert chunk.header_context == "Topic"
        assert chunk.full_text.startswith("Topic\n")


# ==============================================================================
# 3. NumPy Vector Store Tests
# ==============================================================================


def test_numpy_vector_store() -> None:
    store = _NumpyVectorStore(dim=4)
    assert store.ntotal == 0

    v1 = np.array([[1.0, 0.0, 0.0, 0.0]], dtype=np.float32)
    v2 = np.array([[0.0, 1.0, 0.0, 0.0]], dtype=np.float32)
    store.add(v1)
    store.add(v2)
    assert store.ntotal == 2

    # Query matching v1 exactly
    q = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    scores, indices = store.search(q, k=2)
    assert indices[0][0] == 0
    assert pytest.approx(scores[0][0], rel=1e-4) == 1.0
    assert indices[0][1] == 1
    assert pytest.approx(scores[0][1], abs=1e-4) == 0.0


# ==============================================================================
# 4. Pipeline Ingestion & Query Tests (FAISS and NumPy fallback)
# ==============================================================================


@pytest.mark.parametrize("force_numpy", [False, True])
def test_pipeline_ingest_and_query(force_numpy: bool) -> None:
    embedder = MockEmbedder(dim=32)
    pipeline = RAGIngestionPipeline(
        embedding_dim=32,
        embedder=embedder,
        force_numpy=force_numpy,
    )
    assert pipeline._is_faiss == (not force_numpy)

    md1 = """# Knowledge Base
## Python Guide
Python is a readable and versatile programming language.

## Rust Guide
Rust is a systems language focused on safety and high performance.
"""
    count = pipeline.ingest_text(md1, source_file="kb.md")
    assert count == 2
    assert len(pipeline) == 2

    # Query for Python
    res = pipeline.query("Python programming language", top_k=2)
    assert len(res) == 2
    assert isinstance(res[0], RetrievalResult)
    assert "Python" in res[0].chunk.content
    assert res[0].score >= res[1].score


def test_pipeline_empty_query() -> None:
    pipeline = RAGIngestionPipeline(embedding_dim=32)
    assert pipeline.query("anything") == []

    pipeline.ingest_text("# Title\nSome content.")
    assert pipeline.query("") == []
    assert pipeline.query("   ") == []


def test_pipeline_top_k_larger_than_index() -> None:
    pipeline = RAGIngestionPipeline(embedding_dim=32)
    pipeline.ingest_text("# Header\nContent.")
    results = pipeline.query("Content", top_k=10)
    assert len(results) == 1


def test_pipeline_ingest_files(tmp_path: Path) -> None:
    f1 = tmp_path / "doc1.md"
    f1.write_text("# Doc 1\nContent for first document.", encoding="utf-8")

    f2 = tmp_path / "doc2.md"
    f2.write_text("# Doc 2\nContent for second document.", encoding="utf-8")

    pipeline = RAGIngestionPipeline(embedding_dim=32)
    count = pipeline.ingest_files([f1, str(f2)])
    assert count == 2
    assert len(pipeline) == 2

    res = pipeline.query("first document", top_k=1)
    assert len(res) == 1
    assert res[0].chunk.source_file == str(f1)


def test_pipeline_ingest_file_not_found() -> None:
    pipeline = RAGIngestionPipeline(embedding_dim=32)
    with pytest.raises(FileNotFoundError):
        pipeline.ingest_files(["/path/to/nonexistent_file.md"])


# ==============================================================================
# 5. Persistence (Save & Load) Tests
# ==============================================================================


@pytest.mark.parametrize("force_numpy", [False, True])
def test_pipeline_save_and_load(tmp_path: Path, force_numpy: bool) -> None:
    save_dir = tmp_path / f"rag_idx_{force_numpy}"
    embedder = MockEmbedder(dim=32)

    # 1. Create and populate pipeline
    pipeline = RAGIngestionPipeline(
        embedding_dim=32,
        embedder=embedder,
        force_numpy=force_numpy,
    )
    pipeline.ingest_text(
        """# Swarm Engine
The core execution engine coordinates subagents and handles memory persistence.
""",
        source_file="engine.md",
    )
    assert len(pipeline) == 1

    pre_query = pipeline.query("execution engine", top_k=1)
    assert len(pre_query) == 1

    # 2. Save to disk
    pipeline.save(save_dir)
    assert (save_dir / "chunks.json").exists()
    assert (save_dir / "meta.json").exists()

    # 3. Load into a fresh pipeline
    loaded_pipeline = RAGIngestionPipeline(
        embedding_dim=32,
        embedder=embedder,
        force_numpy=force_numpy,
    )
    loaded_pipeline.load(save_dir)
    assert len(loaded_pipeline) == 1
    assert loaded_pipeline.chunks[0].chunk_id == pipeline.chunks[0].chunk_id
    assert loaded_pipeline.chunks[0].full_text == pipeline.chunks[0].full_text

    post_query = loaded_pipeline.query("execution engine", top_k=1)
    assert len(post_query) == 1
    assert post_query[0].chunk.chunk_id == pre_query[0].chunk.chunk_id
    assert pytest.approx(post_query[0].score, rel=1e-3) == pre_query[0].score


def test_cross_backend_load_numpy_from_faiss(tmp_path: Path) -> None:
    """Verify that an index saved with FAISS can be loaded in NumPy mode."""
    save_dir = tmp_path / "cross_backend"
    embedder = MockEmbedder(dim=32)

    p1 = RAGIngestionPipeline(embedding_dim=32, embedder=embedder, force_numpy=False)
    p1.ingest_text("# Title\nSome content.")
    p1.save(save_dir)

    p2 = RAGIngestionPipeline(embedding_dim=32, embedder=embedder, force_numpy=True)
    p2.load(save_dir)
    assert len(p2) == 1
    assert p2._is_faiss is False

    res = p2.query("Some content", top_k=1)
    assert len(res) == 1
    assert res[0].chunk.content == "Some content."


def test_retrieval_module_re_exports() -> None:
    """Verify that DocumentChunk, RetrievalResult, RAGIngestionPipeline are re-exported in swarm_sdk.retrieval."""
    import swarm_sdk.retrieval as ret

    assert hasattr(ret, "DocumentChunk")
    assert hasattr(ret, "RetrievalResult")
    assert hasattr(ret, "RAGIngestionPipeline")
    assert "DocumentChunk" in ret.__all__
    assert "RetrievalResult" in ret.__all__
    assert "RAGIngestionPipeline" in ret.__all__

