"""Tests for the SemanticCache lookup-latency benchmark harness."""

from __future__ import annotations

import numpy as np
from benchmark.Tasks.cache_lookup_latency.benchmark_cache_lookup_latency import (
    TopicEmbedder,
)
from benchmark.Tasks.cache_lookup_latency.benchmark_cache_lookup_latency import (
    run as run_report,
)


def test_topic_embedder_gives_semantic_hits_and_misses_by_design() -> None:
    """Shared-topic texts embed to cosine 1.0; disjoint topics to a lower similarity."""
    embedder = TopicEmbedder()
    stored = embedder.embed(["alpha-1 body one"])
    reworded = embedder.embed(["alpha-1 reworded query"])
    unrelated = embedder.embed(["beta-1 unrelated"])

    cosine_same = float(stored[0] @ reworded[0])
    cosine_other = float(stored[0] @ unrelated[0])
    assert cosine_same > 0.999999
    assert cosine_other < 0.9
    assert embedder.embed([], query=True).shape == (0, embedder.dim)


def test_cache_lookup_latency_report_measures_all_paths() -> None:
    """A quick run returns summaries and a paired ABBA verdict, all measured offline."""
    report = run_report(sizes=(100,), warmup=1, samples=5, blocks=2, batch_size=8)

    assert report["metadata"]["query_embedding_lru_rows"] == 256
    assert report["metadata"]["sizes"] == [100]
    entry = report["results"][0]
    assert entry["entries"] == 100
    for path in ("exact_hit_us", "semantic_hit_us", "miss_us"):
        summary = entry[path]
        assert summary["n"] == 5
        assert summary["median"] > 0
        assert summary["mad"] >= 0
        assert summary["cv_pct"] >= 0
    abba = entry["batch_vs_single"]
    assert abba["batch_size"] == 8
    assert abba["verdict"]["label"] in {
        "B_faster",
        "B_slower",
        "no_detectable_difference",
    }
    assert abba["verdict"]["bootstrap_ci_ms"][0] <= abba["verdict"]["bootstrap_ci_ms"][1]
    assert abba["single_median_per_query_us"] > 0
    assert abba["batch_median_per_query_us"] > 0


def test_lookup_batch_returns_same_answers_as_single_lookup(tmp_path) -> None:
    """The batched API must not change which responses the cache returns."""
    from swarm_sdk.retrieval.cache import SemanticCache

    cache = SemanticCache(str(tmp_path / "cache.db"), TopicEmbedder(), max_entries=1000)
    for i in range(24):
        cache.store(f"topic-{i:03d} body {i}", f"response-{i}")
    queries = [f"topic-{i % 24:03d} reworded {i}" for i in range(24)] + ["topic-999 totally unseen"]
    batched = cache.lookup_batch(queries)
    singles = [cache.lookup(text) for text in queries]
    assert batched == singles
    assert "response-0" in batched
    assert batched[-1] is None


def test_np_float32_rows_are_finite_and_unit_norm() -> None:
    """Every embedder row is a finite float32 vector of unit length."""
    embedder = TopicEmbedder()
    rows = embedder.embed([f"topic-{i} text {i}" for i in range(64)])
    assert rows.dtype == np.float32
    assert np.all(np.isfinite(rows))
    np.testing.assert_allclose(np.linalg.norm(rows, axis=1), 1.0, atol=1e-5)


def run() -> None:
    """Entry point for ``python -m benchmark.run --task cache_lookup_latency``."""
    from benchmark.Tasks.cache_lookup_latency.benchmark_cache_lookup_latency import main

    main(["--quick"])
