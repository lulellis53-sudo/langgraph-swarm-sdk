"""Retrieval metrics over ranked passage ids."""

from __future__ import annotations

from collections.abc import Collection, Sequence


def recall_at_k(ranked: Sequence[str], relevant: Collection[str], k: int) -> float:
    """Return the fraction of ``relevant`` ids found in the first ``k`` ranked ids.

    An empty ``relevant`` set returns 0.0 (the metric is undefined there).

    Raises:
        ValueError: If ``k`` is below 1.
    """
    if k < 1:
        raise ValueError("k must be >= 1")
    if not relevant:
        return 0.0
    found = len(set(ranked[:k]) & set(relevant))
    return found / len(set(relevant))


def mrr(ranked: Sequence[str], relevant: Collection[str]) -> float:
    """Return the reciprocal rank of the first relevant id, or 0.0 when absent."""
    wanted = set(relevant)
    for position, item in enumerate(ranked, start=1):
        if item in wanted:
            return 1.0 / position
    return 0.0


__all__ = ["mrr", "recall_at_k"]
