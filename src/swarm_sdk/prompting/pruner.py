"""Conversation turn pruning: keep recent turns, summarize older ones.

Reduces prompt token usage for long multi-step agent conversations by:
1. Keeping the last ``keep_turns`` turns verbatim (they matter most).
2. Compressing older turns into a rolling extractive digest (no LLM call).
3. Capping the total context at the remaining budget after the system prompt.

Usage::

    pruner = TurnPruner(keep_turns=6, max_tokens=500)
    compressed = pruner.prune(turns)
    packed = budget.pack(system=contract, memories=memories, turns=compressed)
"""

from __future__ import annotations

import re

__all__ = ["TurnPruner", "compress_handoff"]

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _first_sentences(text: str, max_sentences: int = 3) -> str:
    """Return the first *max_sentences* sentences of *text*."""
    sentences = _SENTENCE_SPLIT.split(text.strip())
    return " ".join(sentences[:max_sentences]).strip()


def _set_overlap(a: frozenset[str], b: frozenset[str]) -> float:
    """Jaccard overlap between two precomputed word-sets."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class TurnPruner:
    """Compress conversation turns to fit a token budget.

    Args:
        keep_turns: Number of most-recent turns to keep verbatim.
        max_tokens: Token ceiling for the compressed context (after system prompt).
        summary_sentences: Sentences to extract per older turn for the digest.
    """

    def __init__(
        self,
        *,
        keep_turns: int = 6,
        max_tokens: int = 500,
        summary_sentences: int = 2,
    ) -> None:
        if keep_turns < 1:
            raise ValueError("keep_turns must be >= 1")
        if max_tokens < 1:
            raise ValueError("max_tokens must be >= 1")
        self.keep_turns = keep_turns
        self.max_tokens = max_tokens
        self.summary_sentences = summary_sentences

    def prune(self, turns: list[str]) -> list[str]:
        """Compress *turns*: recent turns verbatim, older turns as a digest.

        Args:
            turns: Conversation turns in chronological order.

        Returns:
            Compressed turns: a single digest line for older turns (if any),
            followed by the last ``keep_turns`` turns unchanged.
        """
        if len(turns) <= self.keep_turns:
            return list(turns)

        older = turns[: -self.keep_turns]
        recent = turns[-self.keep_turns :]

        digest = self._build_digest(older)
        if digest:
            return [digest, *recent]
        return list(recent)

    def _build_digest(self, older: list[str]) -> str:
        """Build a compact extractive digest from older turns.

        Takes the first N sentences of each older turn, deduplicates near-identical
        entries, and joins them into a single ``history:`` line.
        """
        summaries: list[str] = []
        # Word-sets built once per kept summary so the pairwise check is set ops
        # instead of re-splitting both strings on every comparison.
        summary_words: list[frozenset[str]] = []
        for turn in older:
            excerpt = _first_sentences(turn, self.summary_sentences)
            if not excerpt:
                continue
            excerpt_words = frozenset(excerpt.lower().split())
            # Skip near-duplicates to keep the digest small.
            if any(_set_overlap(excerpt_words, s) > 0.85 for s in summary_words):
                continue
            summaries.append(excerpt)
            summary_words.append(excerpt_words)

        if not summaries:
            return ""
        body = " | ".join(summaries)
        return f"history: {body}"


def compress_handoff(
    output: str,
    *,
    max_tokens: int = 500,
    summary_sentences: int = 3,
) -> str:
    """Compress a dependency output for injection into a step prompt.

    Uses extractive summarization: keeps the first ``summary_sentences`` sentences
    and truncates to ``max_tokens``. No LLM call.

    Args:
        output: Full dependency output text.
        max_tokens: Token ceiling for the compressed result.
        summary_sentences: Sentences to keep from the beginning.

    Returns:
        Compressed text, or the original if already short enough.
    """
    from swarm_sdk.prompting.budget import count_text

    if not output:
        return ""
    if count_text(output) <= max_tokens:
        return output

    excerpt = _first_sentences(output, summary_sentences)
    if count_text(excerpt) <= max_tokens:
        return excerpt

    # Binary search for the longest prefix that fits.
    best = ""
    lo, hi = 0, len(excerpt)
    while lo <= hi:
        mid = (lo + hi) // 2
        piece = excerpt[:mid].rstrip()
        if piece and count_text(piece) <= max_tokens:
            best = piece
            lo = mid + 1
        else:
            hi = mid - 1
    return best
