"""Tests for the isolated SQLite and optional DuckDB cache benchmark."""

from __future__ import annotations

from benchmark.Tasks.cache_storage.benchmark_cache_storage import run


def test_cache_storage_benchmark_isolates_sqlite_measurements() -> None:
    """Return SQLite latency and resource samples without requiring DuckDB."""
    report = run(sizes=(8,), rounds=1, iterations=2)

    assert report["metadata"]["isolated_process_per_engine_and_size"] is True
    assert report["results"]
    assert report["results"][0]["engine"] == "sqlite"
    assert report["results"][0]["peak_rss_bytes"] > 0
    assert set(report["results"][0]["timings"]) == {
        "exact_hit",
        "exact_miss",
        "semantic_scan",
        "insert",
    }
