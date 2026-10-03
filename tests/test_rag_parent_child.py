"""Parent-child (small-to-big) chunking in RAGIngestionPipeline."""

from __future__ import annotations

from pathlib import Path

import pytest
from benchmark.Tasks.rag_quality.embedders import BagOfWordsEmbedder

from swarm_sdk.retrieval.rag_ingest import RAGIngestionPipeline, split_children

DOC = (
    "# Guide\n\n## Cache\n\n"
    "The semantic cache stores answers. Entries expire after days. "
    "Empty answers are never cached. Lookups use cosine similarity.\n\n"
    "## Vault\n\nKeys live in the Keychain and never in YAML files.\n"
)


def test_split_children_respects_size_and_preserves_words() -> None:
    text = "one two three four five six seven"
    parts = split_children(text, 10)
    assert all(len(p) <= 10 for p in parts)
    assert " ".join(parts).split() == text.split()


def test_split_children_edge_cases() -> None:
    assert split_children("", 10) == []
    assert split_children("   ", 10) == []
    assert split_children("abcdefghijklmnop", 5) == [
        "abcdefghijklmnop"
    ]  # one long word stays whole
    assert split_children("café 東京 ß", 6) == ["café", "東京 ß"]
    with pytest.raises(ValueError):
        split_children("x", 0)


def test_child_size_must_be_positive() -> None:
    with pytest.raises(ValueError):
        RAGIngestionPipeline(child_size=0)


def test_default_pipeline_is_unchanged() -> None:
    pipeline = RAGIngestionPipeline(force_numpy=True)
    n = pipeline.ingest_text(DOC)
    assert len(pipeline.chunks) == n
    assert all("parent_id" not in c.metadata for c in pipeline.chunks)


def test_children_are_indexed_but_parents_are_returned() -> None:
    pipeline = RAGIngestionPipeline(embedder=BagOfWordsEmbedder(), child_size=40, force_numpy=True)
    pipeline.ingest_text(DOC)
    assert len(pipeline.chunks) > len(pipeline._parents)
    results = pipeline.query("empty answers cached", top_k=2)
    parent_ids = [r.chunk.chunk_id for r in results]
    assert len(parent_ids) == len(set(parent_ids))  # deduplicated by parent
    assert "Empty answers are never cached" in results[0].chunk.content
    assert len(results[0].chunk.content) > 40  # the full parent, not the child


def test_reingesting_the_same_source_does_not_collide() -> None:
    pipeline = RAGIngestionPipeline(child_size=40, force_numpy=True)
    pipeline.ingest_text(DOC, source_file="a.md")
    after_first = len(pipeline._parents)
    pipeline.ingest_text(DOC, source_file="a.md")
    assert after_first > 0
    assert len(pipeline._parents) == 2 * after_first  # no id reuse across ingests


def test_save_and_load_round_trip_returns_the_same_parents(tmp_path: Path) -> None:
    embedder = BagOfWordsEmbedder()
    pipeline = RAGIngestionPipeline(embedder=embedder, child_size=40, force_numpy=True)
    pipeline.ingest_text(DOC)
    expected = [r.chunk.content for r in pipeline.query("keychain yaml", top_k=2)]
    assert expected
    pipeline.save(tmp_path)
    restored = RAGIngestionPipeline(embedder=embedder, child_size=40, force_numpy=True)
    restored.load(tmp_path)
    assert [r.chunk.content for r in restored.query("keychain yaml", top_k=2)] == expected


def test_empty_query_and_empty_pipeline_return_nothing() -> None:
    pipeline = RAGIngestionPipeline(embedder=BagOfWordsEmbedder(), child_size=40, force_numpy=True)
    assert pipeline.query("anything") == []
    pipeline.ingest_text(DOC)
    assert pipeline.query("   ") == []


def test_top_k_distinct_parents_even_when_one_parent_dominates() -> None:
    big = "gamma " * 80  # splits into many children that all match the query best
    doc = "## Big\n\n" + big + "\n\n" + "\n\n".join(f"## O{i}\n\nother text {i}" for i in range(5))
    pipeline = RAGIngestionPipeline(embedder=BagOfWordsEmbedder(), child_size=10, force_numpy=True)
    pipeline.ingest_text(doc)
    assert len(pipeline.chunks) > 12  # more children than top_k * 4
    results = pipeline.query("gamma", top_k=3)
    assert len(results) == 3
    assert len({r.chunk.chunk_id for r in results}) == 3


def test_load_restores_child_size_from_the_index(tmp_path: Path) -> None:
    embedder = BagOfWordsEmbedder()
    pipeline = RAGIngestionPipeline(embedder=embedder, child_size=40, force_numpy=True)
    pipeline.ingest_text(DOC)
    pipeline.save(tmp_path)
    restored = RAGIngestionPipeline(embedder=embedder, force_numpy=True)  # child_size=None
    restored.load(tmp_path)
    assert restored.child_size == 40
    restored.ingest_text(DOC, source_file="b.md")
    assert all("parent_id" in c.metadata for c in restored.chunks)


def test_load_rejects_a_mismatched_child_size(tmp_path: Path) -> None:
    embedder = BagOfWordsEmbedder()
    flat = RAGIngestionPipeline(embedder=embedder, force_numpy=True)
    flat.ingest_text(DOC)
    flat.save(tmp_path / "flat")
    with pytest.raises(ValueError, match="child_size"):
        RAGIngestionPipeline(embedder=embedder, child_size=40, force_numpy=True).load(
            tmp_path / "flat"
        )
    nested = RAGIngestionPipeline(embedder=embedder, child_size=40, force_numpy=True)
    nested.ingest_text(DOC)
    nested.save(tmp_path / "nested")
    with pytest.raises(ValueError, match="child_size"):
        RAGIngestionPipeline(embedder=embedder, child_size=80, force_numpy=True).load(
            tmp_path / "nested"
        )
