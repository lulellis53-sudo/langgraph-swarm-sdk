"""Knowledge-strip refinement tests (no network, no heavy optional stacks)."""

from __future__ import annotations

from swarm_sdk.retrieval.gate import Confidence, GateConfig
from swarm_sdk.retrieval.rag_ingest import DocumentChunk
from swarm_sdk.retrieval.strips import (
    KnowledgeStrip,
    refine_strips,
    score_strip,
    segment_sentences,
)


def _chunk(chunk_id: str, text: str) -> DocumentChunk:
    """Build a minimal chunk with ``text`` as its full text."""
    return DocumentChunk(
        chunk_id=chunk_id,
        source_file="doc.md",
        header_context="Header",
        content=text,
        full_text=text,
    )


def test_segment_sentences_splits_on_terminal_punctuation() -> None:
    """Sentences split at terminal punctuation and drop sub-10-character fragments."""
    assert segment_sentences("First sentence here. Second sentence here! Third?") == [
        "First sentence here.",
        "Second sentence here!",
    ]


def test_segment_sentences_keeps_long_text_whole() -> None:
    """A passage without terminal punctuation stays a single strip."""
    assert segment_sentences("no punctuation at all in this passage") == [
        "no punctuation at all in this passage"
    ]


def test_score_strip_is_fraction_of_matched_query_terms() -> None:
    """Score is the share of distinct query terms present in the strip."""
    terms = frozenset({"vector", "search", "embeddings"})
    assert score_strip("vector search uses embeddings", terms) == 1.0
    assert round(score_strip("vector search", terms), 4) == 0.6667
    assert score_strip("gardening tips", terms) == 0.0


def test_score_strip_without_terms_is_zero() -> None:
    """An empty query scores every strip at zero rather than raising."""
    assert score_strip("anything", frozenset()) == 0.0


def test_refine_strips_returns_strips_and_retained_texts() -> None:
    """Relevant sentences are retained; unrelated ones are not."""
    chunks = [_chunk("c1", "Vector search uses embeddings. Gardening is unrelated entirely.")]
    result = refine_strips("vector embeddings retrieval", chunks)
    assert isinstance(result.strips[0], KnowledgeStrip)
    assert len(result.strips) == 2
    assert any("embeddings" in text for text in result.retained_texts)
    assert not any("Gardening" in text for text in result.retained_texts)


def test_refine_strips_low_confidence_on_weak_overlap() -> None:
    """Weak overlap grades LOW using the gate's low threshold."""
    chunks = [_chunk("c1", "Nothing relevant appears in this passage at all.")]
    result = refine_strips("vector embeddings retrieval", chunks)
    assert result.confidence is Confidence.LOW


def test_refine_strips_high_confidence_on_full_overlap() -> None:
    """Full term overlap grades HIGH using the gate's high threshold."""
    chunks = [_chunk("c1", "vector embeddings retrieval pipeline")]
    result = refine_strips("vector embeddings retrieval", chunks)
    assert result.confidence is Confidence.HIGH


def test_refine_strips_ambiguous_between_thresholds() -> None:
    """A mean score between low and high grades AMBIGUOUS."""
    config = GateConfig(high=0.9, low=0.1)
    result = refine_strips(
        "vector embeddings retrieval search ranking",
        [_chunk("c1", "vector embeddings appear here. Nothing else matches here.")],
        config=config,
    )
    assert result.confidence is Confidence.AMBIGUOUS


def test_refine_strips_handles_empty_inputs() -> None:
    """No chunks and no query both grade LOW without raising."""
    assert refine_strips("query", []).confidence is Confidence.LOW
    assert refine_strips("", [_chunk("c1", "some text that is long enough")]).mean_score == 0.0


def test_refine_strips_accepts_scored_tuples() -> None:
    """BM25-style ``(chunk, score)`` pairs are accepted like bare chunks."""
    scored = [(_chunk("c1", "embeddings everywhere in this text"), 0.9)]
    result = refine_strips("embeddings", scored)
    assert result.strips[0].chunk_id == "c1"


def test_refine_strips_skips_chunks_without_text() -> None:
    """Chunks carrying no text contribute no strips."""
    empty = DocumentChunk(
        chunk_id="c2", source_file="d.md", header_context="H", content="", full_text=""
    )
    assert refine_strips("query", [empty]).strips == []


def test_retained_count_matches_retained_flag() -> None:
    """``retained_count`` equals the number of strips flagged retained."""
    result = refine_strips("vector", [_chunk("c1", "vector one. unrelated text here. vector two.")])
    assert result.retained_count == sum(1 for s in result.strips if s.is_retained)
