"""Compare paired Redis and SQLite response-cache paths.

The benchmark requires a real Redis URL unless ``allow_memory`` is explicitly
enabled by tests. It writes raw paired samples and statistical summaries but
does not claim a speedup from one process run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import resource
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, ClassVar

import numpy as np
from benchmark.protocol import (
    TAIL_MIN_N,
    abba,
    allows_speedup_claim,
    bootstrap_median_ci,
    paired_deltas,
    summarize,
)

from swarm_sdk.retrieval.cache import SemanticCache
from swarm_sdk.retrieval.embeddings import Embedder
from swarm_sdk.retrieval.redis_exact import RedisExactCache

_DEFAULT_SIZES = (100, 1_000, 10_000)
_DEFAULT_ROUNDS = 50
_DEFAULT_ITERATIONS = 500
_WARMUP_BATCHES = 3
_BOOTSTRAP_RESAMPLES = 2_000


class _MemoryRedis:
    """Implement the redis-py surface used by RedisExactCache in unit tests."""

    values: ClassVar[dict[str, bytes]] = {}

    @classmethod
    def from_url(cls, url: str, **options: object) -> _MemoryRedis:
        """Return a shared in-memory client."""
        del url, options
        return cls()

    def get(self, key: str) -> bytes | None:
        """Return one in-memory value."""
        return self.values.get(key)

    def set(self, key: str, value: bytes, *, ex: int) -> bool:
        """Store one value and accept its expiration argument."""
        del ex
        self.values[key] = value
        return True

    def ping(self) -> bool:
        """Report that the stand-in is available."""
        return True

    def info(self, section: str) -> dict[str, str]:
        """Return deterministic server metadata."""
        del section
        return {"redis_version": "in-memory"}


class _FixedEmbedder(Embedder):
    """Return orthogonal fixed vectors for stored rows and semantic misses."""

    dim = 2

    def embed(self, texts: list[str], *, query: bool = False) -> np.ndarray:
        """Return the query vector or a row vector for each input text."""
        del query
        return np.asarray(
            [[0.0, 1.0] if text.startswith("miss") else [1.0, 0.0] for text in texts],
            dtype=np.float32,
        )


def _memory_redis_module() -> ModuleType:
    """Build a redis-py-shaped module backed by the local test stand-in."""
    module = ModuleType("redis")
    setattr(module, "Redis", _MemoryRedis)
    setattr(module, "exceptions", SimpleNamespace(RedisError=RuntimeError))
    return module


def _redis_cache(
    url: str | None,
    *,
    namespace: str,
    allow_memory: bool,
) -> tuple[RedisExactCache, str, str]:
    """Create an isolated Redis cache and return its mode and server version."""
    if url:
        cache = RedisExactCache(url, namespace, 3600)
        cache._redis.ping()
        info = cache._redis.info("server")
        version = str(info.get("redis_version", "unknown"))
        return cache, "real", version
    if not allow_memory:
        raise ValueError("set REDIS_URL to run against Redis, or enable memory mode for tests")

    previous = sys.modules.get("redis")
    sys.modules["redis"] = _memory_redis_module()
    try:
        cache = RedisExactCache("redis://memory.invalid/0", namespace, 3600)
    finally:
        if previous is None:
            sys.modules.pop("redis", None)
        else:
            sys.modules["redis"] = previous
    return cache, "memory", "in-memory"


def _seed_exact_cache(size: int, *, redis_cache: RedisExactCache | None = None) -> SemanticCache:
    """Build a cache with deterministic exact rows and an optional Redis layer."""
    cache = SemanticCache(":memory:", _FixedEmbedder(), threshold=0.99, max_entries=size + 1)
    rows = [
        (
            hashlib.sha256(f"key-{index}".encode()).hexdigest(),
            f"response-{index}",
            "default",
            float(index),
        )
        for index in range(size)
    ]
    cache._conn.executemany(
        "INSERT INTO exact_cache(key, response, tenant_id, inserted_at) VALUES (?, ?, ?, ?)",
        rows,
    )
    cache._conn.commit()
    cache._redis_cache = redis_cache
    return cache


def _seed_semantic_cache(size: int, *, redis_cache: RedisExactCache | None = None) -> SemanticCache:
    """Build a cache with deterministic semantic rows and an optional Redis layer."""
    cache = SemanticCache(":memory:", _FixedEmbedder(), threshold=0.99, max_entries=size + 1)
    vector = np.asarray([1.0, 0.0], dtype="<f4").tobytes()
    cache._conn.executemany(
        """
        INSERT INTO semantic_cache(
            query_text, vector, response, tenant_id, inserted_at, accessed_at
        ) VALUES (?, ?, ?, 'default', 0, 0)
        """,
        [(f"stored-{index}", vector, "row") for index in range(size)],
    )
    cache._conn.commit()
    cache._redis_cache = redis_cache
    return cache


def _time_batch(operation: Callable[[], object], *, iterations: int) -> float:
    """Return mean milliseconds per operation for one timed batch."""
    started = time.perf_counter_ns()
    for _ in range(iterations):
        operation()
    return (time.perf_counter_ns() - started) / iterations / 1_000_000


def _peak_rss_bytes() -> int:
    """Return process peak RSS in bytes on macOS and Linux."""
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def _compare(
    name: str,
    size: int,
    baseline: Callable[[], object],
    candidate: Callable[[], object],
    *,
    rounds: int,
    iterations: int,
) -> dict[str, Any]:
    """Return paired ABBA timings, robust summaries, and a seeded CI."""
    cpu_started = time.process_time_ns()
    for _ in range(_WARMUP_BATCHES):
        _time_batch(baseline, iterations=iterations)
        _time_batch(candidate, iterations=iterations)
    baseline_samples, candidate_samples = abba(
        lambda: _time_batch(baseline, iterations=iterations),
        lambda: _time_batch(candidate, iterations=iterations),
        rounds=rounds,
    )
    deltas = paired_deltas(candidate_samples, baseline_samples)
    delta_summary = summarize(deltas)
    seed = sum(name.encode("utf-8")) + size
    confidence_interval = bootstrap_median_ci(
        deltas, resamples=_BOOTSTRAP_RESAMPLES, confidence=0.95, seed=seed
    )
    return {
        "size": size,
        "name": name,
        "baseline": summarize(baseline_samples),
        "candidate": summarize(candidate_samples),
        "paired_delta_candidate_minus_baseline": delta_summary,
        "paired_delta_ci95_ms": list(confidence_interval),
        "speedup_claim_allowed": allows_speedup_claim(
            delta=delta_summary["median"],
            dispersion=delta_summary["mad"],
            independent_runs=1,
        ),
        "samples_ms": {
            "baseline": baseline_samples,
            "candidate": candidate_samples,
            "paired_delta": deltas,
        },
        "process_cpu_ms": (time.process_time_ns() - cpu_started) / 1_000_000,
    }


def run(
    *,
    sizes: tuple[int, ...] = _DEFAULT_SIZES,
    rounds: int = _DEFAULT_ROUNDS,
    iterations: int = _DEFAULT_ITERATIONS,
    redis_url: str | None = None,
    allow_memory: bool = False,
) -> dict[str, Any]:
    """Measure paired SQLite and Redis cache paths and return JSON-safe results.

    Args:
        sizes: Exact and semantic rows to load for each measurement.
        rounds: Number of ABBA rounds; two paired samples are collected per round.
        iterations: Operations in each timed batch.
        redis_url: Redis service URL; defaults to the ``REDIS_URL`` environment variable.
        allow_memory: Permit the in-memory stand-in for unit tests only.

    Returns:
        Metadata, raw paired samples, and protocol summaries for each workload.

    Raises:
        ValueError: If settings are invalid or Redis is not configured.
        redis.exceptions.RedisError: If the configured Redis service is unavailable.
    """
    if not sizes or any(size < 1 for size in sizes):
        raise ValueError("sizes must contain positive row counts")
    if rounds < 1 or iterations < 1:
        raise ValueError("rounds and iterations must be positive")
    url = redis_url or os.environ.get("REDIS_URL")
    run_id = uuid.uuid4().hex
    clients: list[RedisExactCache] = []
    redis_mode: str | None = None
    redis_version: str | None = None
    comparisons: list[dict[str, Any]] = []
    try:

        def make_client(size: int, name: str) -> RedisExactCache:
            """Create and track one uniquely namespaced Redis client."""
            nonlocal redis_mode, redis_version
            client, mode, version = _redis_cache(
                url,
                namespace=f"benchmark:response:{run_id}:{size}:{name}",
                allow_memory=allow_memory,
            )
            clients.append(client)
            redis_mode = mode
            redis_version = version
            return client

        for size in sizes:
            target = f"key-{size - 1}"
            response = f"response-{size - 1}"
            sqlite_exact = _seed_exact_cache(size)
            redis_hit_client = make_client(size, "exact-hit")
            redis_hit_client.set(f"default:{target}", response)
            redis_exact = _seed_exact_cache(size, redis_cache=redis_hit_client)
            if sqlite_exact.lookup(target) != response or redis_exact.lookup(target) != response:
                raise RuntimeError("exact-hit benchmark setup returned an unexpected response")
            comparisons.append(
                _compare(
                    "exact_hit_sqlite_vs_redis",
                    size,
                    lambda: sqlite_exact.lookup(target),
                    lambda: redis_exact.lookup(target),
                    rounds=rounds,
                    iterations=iterations,
                )
            )

            fallback_base = _seed_exact_cache(size)
            fallback_client = make_client(size, "redis-miss-exact-fallback")
            fallback_candidate = _seed_exact_cache(size, redis_cache=fallback_client)
            exact_fallback_responses = (
                fallback_base.lookup(target),
                fallback_candidate.lookup(target),
            )
            if exact_fallback_responses != (response, response):
                raise RuntimeError("unexpected response from exact fallback setup")
            comparisons.append(
                _compare(
                    "redis_miss_sqlite_exact_fallback",
                    size,
                    lambda: fallback_base.lookup(target),
                    lambda: fallback_candidate.lookup(target),
                    rounds=rounds,
                    iterations=iterations,
                )
            )

            semantic_base = _seed_semantic_cache(size)
            semantic_client = make_client(size, "redis-miss-semantic-fallback")
            semantic_candidate = _seed_semantic_cache(size, redis_cache=semantic_client)
            query = "miss-query"
            semantic_miss_responses = (
                semantic_base.lookup(query),
                semantic_candidate.lookup(query),
            )
            if semantic_miss_responses != (None, None):
                raise RuntimeError("semantic-miss benchmark setup returned a cached response")
            comparisons.append(
                _compare(
                    "semantic_miss_sqlite_vs_redis_fallback",
                    size,
                    lambda: semantic_base.lookup(query),
                    lambda: semantic_candidate.lookup(query),
                    rounds=rounds,
                    iterations=iterations,
                )
            )

        return {
            "metadata": {
                "protocol": "ABBA paired batch timings",
                "python_version": platform.python_version(),
                "platform": platform.platform(),
                "redis_mode": redis_mode,
                "redis_version": redis_version,
                "sizes": list(sizes),
                "rounds": rounds,
                "pair_samples_per_comparison": rounds * 2,
                "iterations_per_sample": iterations,
                "warmup_batches_per_variant": _WARMUP_BATCHES,
                "tail_min_samples": TAIL_MIN_N,
                "bootstrap_resamples": _BOOTSTRAP_RESAMPLES,
                "independent_runs": 1,
            },
            "comparisons": comparisons,
            "peak_rss_bytes": _peak_rss_bytes(),
        }
    finally:
        for client in clients:
            close = getattr(client._redis, "close", None)
            if callable(close):
                close()


def main(argv: list[str] | None = None) -> int:
    """Run the Redis benchmark and print or save its JSON report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+", default=list(_DEFAULT_SIZES))
    parser.add_argument("--rounds", type=int, default=_DEFAULT_ROUNDS)
    parser.add_argument("--iterations", type=int, default=_DEFAULT_ITERATIONS)
    parser.add_argument("--write-results", action="store_true")
    args = parser.parse_args(argv)
    report = run(sizes=tuple(args.sizes), rounds=args.rounds, iterations=args.iterations)
    rendered = json.dumps(report, indent=2)
    print(rendered)
    if args.write_results:
        results_dir = Path(__file__).resolve().parents[2] / "results" / "redis_cache"
        results_dir.mkdir(parents=True, exist_ok=True)
        (results_dir / "latest.json").write_text(rendered + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
