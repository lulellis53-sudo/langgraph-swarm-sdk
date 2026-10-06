"""CI check for the rag_quality benchmark: fixture integrity and baseline report shape."""

from __future__ import annotations

import pytest
from benchmark.Tasks.rag_quality.benchmark_rag_quality import evaluate, load_fixture, run
from benchmark.Tasks.rag_quality.embedders import BagOfWordsEmbedder


def test_bag_of_words_embedder_is_deterministic_and_lexical() -> None:
    embedder = BagOfWordsEmbedder()
    a, b, c = embedder.embed(["sqlite vector memory", "sqlite vector memory", "pasta recipe"])
    assert (a == b).all()
    assert float(a @ a) == pytest.approx(1.0)
    related = embedder.embed(["vector memory store"])[0]
    assert float(a @ related) > float(a @ c)
    assert embedder.embed([""])[0].sum() == 0.0  # empty text stays the zero vector


def test_fixture_is_consistent() -> None:
    passages, queries = load_fixture()
    ids = {p.id for p in passages}
    assert len(ids) == len(passages) == 24
    assert len(queries) == 12
    assert all(set(q.relevant) <= ids for q in queries)
    assert sum(1 for q in queries if not q.relevant) == 2


def test_evaluate_scores_a_perfect_and_an_empty_ranker() -> None:
    _, queries = load_fixture()
    relevant = {q.q: list(q.relevant) for q in queries}
    perfect = evaluate(lambda q: relevant[q], queries, k=3)
    assert perfect["mrr"] == 1.0
    assert perfect["false_inject_rate"] == 0.0
    empty = evaluate(lambda q: [], queries, k=3)
    assert empty == {"recall_at_k": 0.0, "mrr": 0.0, "false_inject_rate": 0.0}


def test_baseline_run_reports_bounded_metrics() -> None:
    report = run()
    row = report["variants"]["baseline"]
    assert set(row) == {"recall_at_k", "mrr", "false_inject_rate"}
    assert all(0.0 <= value <= 1.0 for value in row.values())
    assert row["recall_at_k"] > 0.0  # the fixture is retrievable at all
    assert row["false_inject_rate"] == 1.0  # ungated recall always injects something


def test_gate_variant_removes_false_injection_without_losing_recall() -> None:
    report = run()
    base, gated = report["variants"]["baseline"], report["variants"]["gate"]
    assert gated["false_inject_rate"] == 0.0
    assert gated["recall_at_k"] >= base["recall_at_k"] - 1e-9
    assert gated["mrr"] >= base["mrr"] - 1e-9


def test_pipeline_variants_are_reported() -> None:
    report = run()
    assert {"pipeline_flat", "pipeline_parent_child"} <= set(report["variants"])
    for name in ("pipeline_flat", "pipeline_parent_child"):
        assert all(0.0 <= v <= 1.0 for v in report["variants"][name].values())
