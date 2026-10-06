"""Tests for the paired Redis cache benchmark report."""

from __future__ import annotations

import json

import pytest
from benchmark.Tasks.redis_cache.benchmark_redis_cache import _MemoryRedis, run


def test_benchmark_reports_paired_cache_paths_without_service() -> None:
    """Return paired summaries and raw samples with the in-memory Redis stand-in."""
    report = run(sizes=(8,), rounds=1, iterations=2, allow_memory=True)

    assert report["metadata"]["redis_mode"] == "memory"
    assert report["metadata"]["pair_samples_per_comparison"] == 2
    assert len(report["comparisons"]) == 3
    for comparison in report["comparisons"]:
        assert len(comparison["samples_ms"]["baseline"]) == 2
        assert len(comparison["samples_ms"]["candidate"]) == 2
        assert len(comparison["samples_ms"]["paired_delta"]) == 2
        assert comparison["baseline"]["tail_supported"] is False
        assert comparison["candidate"]["tail_supported"] is False
        assert comparison["speedup_claim_allowed"] is False
    json.dumps(report)


def test_benchmark_requires_real_redis_unless_memory_mode_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not silently present in-memory measurements as Redis measurements."""
    monkeypatch.delenv("REDIS_URL", raising=False)

    with pytest.raises(ValueError, match="REDIS_URL"):
        run(sizes=(2,), rounds=1, iterations=1)


def test_benchmark_uses_a_fresh_redis_namespace_for_each_run() -> None:
    """Avoid collisions with old or concurrent benchmark keys."""
    _MemoryRedis.values.clear()
    run(sizes=(2,), rounds=1, iterations=1, allow_memory=True)
    first_run_keys = set(_MemoryRedis.values)
    run(sizes=(2,), rounds=1, iterations=1, allow_memory=True)
    second_run_keys = set(_MemoryRedis.values) - first_run_keys

    assert first_run_keys
    assert second_run_keys
    assert first_run_keys.isdisjoint(second_run_keys)


@pytest.mark.parametrize(
    ("sizes", "rounds", "iterations"),
    [((0,), 1, 1), ((1,), 0, 1), ((1,), 1, 0)],
)
def test_benchmark_rejects_invalid_workloads(
    sizes: tuple[int, ...], rounds: int, iterations: int
) -> None:
    """Reject invalid benchmark settings before opening Redis or SQLite."""
    with pytest.raises(ValueError):
        run(sizes=sizes, rounds=rounds, iterations=iterations, allow_memory=True)
