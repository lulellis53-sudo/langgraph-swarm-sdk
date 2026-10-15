"""Unit tests for the retrieval metrics."""

from __future__ import annotations

import pytest
from benchmark.Tasks.rag_quality.metrics import mrr, recall_at_k


def test_recall_at_k_counts_relevant_in_top_k() -> None:
    assert recall_at_k(["a", "b", "c"], {"a", "c"}, 2) == pytest.approx(0.5)
    assert recall_at_k(["a", "b", "c"], {"a", "c"}, 3) == pytest.approx(1.0)


def test_recall_at_k_edge_cases() -> None:
    assert recall_at_k([], {"a"}, 3) == 0.0
    assert recall_at_k(["a"], set(), 3) == 0.0  # no relevant ids: undefined, reported as 0
    with pytest.raises(ValueError):
        recall_at_k(["a"], {"a"}, 0)


def test_mrr_is_reciprocal_rank_of_first_relevant() -> None:
    assert mrr(["x", "a", "b"], {"a", "b"}) == pytest.approx(0.5)
    assert mrr(["a"], {"a"}) == 1.0
    assert mrr(["x", "y"], {"a"}) == 0.0
    assert mrr([], {"a"}) == 0.0
