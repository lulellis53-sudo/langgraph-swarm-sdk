"""Tests for the Redis cache benchmark report and local-only mode."""

from __future__ import annotations

from benchmark.Tasks.redis_cache.benchmark_redis_cache import run


def test_benchmark_reports_cache_paths_without_redis_service(monkeypatch) -> None:
    """Measure both cache paths using the local Redis stand-in."""
    monkeypatch.delenv("REDIS_URL", raising=False)
    report = run(sizes=(8,), rounds=2, iterations=3)

    assert report["redis_mode"] == "memory"
    assert report["results"]
    names = {result["name"] for result in report["results"]}
    assert names == {"sqlite_exact_hit", "redis_exact_hit", "semantic_miss"}
    assert all(result["p50_ms"] >= 0 for result in report["results"])
    assert all(result["p95_ms"] >= result["p50_ms"] for result in report["results"])
