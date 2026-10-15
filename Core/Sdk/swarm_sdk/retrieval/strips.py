"""Knowledge-strip refinement for corrective retrieval (CRAG, Yan et al., 2024).

Module-level sentence segmentation of retrieved chunks, per-strip relevance
scoring, and aggregation into the existing :class:`~swarm_sdk.retrieval.gate.Confidence`
buckets. The gate in ``gate.py`` classifies on the *best* reranker score; this
module classifies on the *mean* strip score, so the two are complementary and
must not be swapped for one another.

Only the standard library is imported eagerly; nothing here pulls in a heavy
optional stack at import time.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, Field

from swarm_sdk.retrieval.gate import Confidence, GateConfig

# Sentence boundary: terminal punctuation followed by whitespace. Deliberately
# simple - a full segmenter would need a heavy NLP dependency for a rule this
# predictable, and retrieval strips tolerate occasional over-splitting.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

# Strips shorter than this carry too little signal to grade meaningfully.
_MIN_STRIP_CHARS = 10


class KnowledgeStrip(BaseModel):
    """One graded sentence-level strip extracted from a retrieved chunk."""

    strip_id: str
    chunk_id: str
    text: str
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    is_retained: bool = True


class StripRefinement(BaseModel):
    """Outcome of strip-level refinement over a ranked retrieval result."""

    confidence: Confidence
    mean_score: float = Field(ge=0.0, le=1.0)
    strips: list[KnowledgeStrip] = Field(default_factory=list)
    retained_texts: list[str] = Field(default_factory=list)

    @property
    def retained_count(self) -> int:
        """Number of strips kept as relevant context."""
        return sum(1 for strip in self.strips if strip.is_retained)


def segment_sentences(text: str) -> list[str]:
    """Split ``text`` into sentence-level strips of at least ten characters.

    Args:
        text: Raw passage text.

    Returns:
        Sentence strips in document order.
    """
    parts = (part.strip() for part in _SENTENCE_SPLIT.split(text))
    return [part for part in parts if len(part) >= _MIN_STRIP_CHARS]


def score_strip(strip: str, query_terms: frozenset[str]) -> float:
    """Score one strip by the fraction of distinct query terms it contains.

    Args:
        strip: Candidate sentence.
        query_terms: Lower-cased, de-duplicated query tokens.

    Returns:
        A value in ``[0.0, 1.0]``.
    """
    if not query_terms:
        return 0.0
    stripped_terms = set(strip.lower().split())
    return min(len(stripped_terms & query_terms) / len(query_terms), 1.0)


def _chunk_pair(candidate: Any) -> tuple[str, str]:
    """Return ``(chunk_id, text)`` for a chunk, result, or ``(obj, score)`` tuple.

    Accepts the shapes the retrieval layer already produces: a
    :class:`~swarm_sdk.retrieval.rag_ingest.DocumentChunk`, a
    :class:`~swarm_sdk.retrieval.rag_ingest.RetrievalResult`, or a plain
    ``(object, score)`` pair as returned by BM25 search.
    """
    obj: Any = candidate[0] if isinstance(candidate, tuple) and candidate else candidate
    # RetrievalResult wraps its chunk; DocumentChunk and ad-hoc objects do not.
    inner: Any = getattr(obj, "chunk", None) or obj
    chunk_id = str(getattr(inner, "chunk_id", "") or "")
    text = str(
        getattr(inner, "full_text", None)
        or getattr(inner, "content", None)
        or getattr(inner, "text", None)
        or ""
    )
    return chunk_id, text


def refine_strips(
    query: str,
    chunks: Sequence[Any],
    *,
    config: GateConfig | None = None,
) -> StripRefinement:
    """Segment, score, and grade retrieved chunks into retained knowledge strips.

    Args:
        query: The user query driving retrieval.
        chunks: Retrieved chunks, results, or ``(chunk, score)`` pairs.
        config: Gate thresholds; defaults to :class:`GateConfig`.

    Returns:
        A :class:`StripRefinement` whose ``confidence`` uses the same
        ``high``/``low`` thresholds as ``gate.classify`` but grades the mean
        strip score rather than the best score.
    """
    gate = config or GateConfig()
    query_terms = frozenset(query.lower().split())
    strips: list[KnowledgeStrip] = []

    for candidate in chunks:
        chunk_id, text = _chunk_pair(candidate)
        if not text:
            continue
        for index, sentence in enumerate(segment_sentences(text)):
            score = score_strip(sentence, query_terms)
            strips.append(
                KnowledgeStrip(
                    strip_id=f"{chunk_id or 'chunk'}_s{index}",
                    chunk_id=chunk_id,
                    text=sentence,
                    relevance_score=round(score, 4),
                    is_retained=score >= gate.low,
                )
            )

    mean_score = round(sum(s.relevance_score for s in strips) / len(strips), 4) if strips else 0.0

    if not strips or mean_score < gate.low:
        confidence = Confidence.LOW
    elif mean_score >= gate.high:
        confidence = Confidence.HIGH
    else:
        confidence = Confidence.AMBIGUOUS

    return StripRefinement(
        confidence=confidence,
        mean_score=mean_score,
        strips=strips,
        retained_texts=[s.text for s in strips if s.is_retained],
    )


__all__ = [
    "KnowledgeStrip",
    "StripRefinement",
    "refine_strips",
    "score_strip",
    "segment_sentences",
]
