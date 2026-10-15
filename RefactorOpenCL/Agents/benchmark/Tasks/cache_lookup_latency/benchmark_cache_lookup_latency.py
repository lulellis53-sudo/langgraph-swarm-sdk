"""SemanticCache lookup-path latency: exact hit, semantic hit, and miss by cache size.

Measures the shipped ``SemanticCache.lookup`` path with rotating distinct queries so the
bounded query-embedding LRU (256 rows) never serves a warm vector, then compares the
batched ``lookup_batch`` against per-query ``lookup`` with the ABBA paired protocol from
``benchmark.stats`` (Benchmark.md §2.6). Offline and key-free: the semantic layer uses a
deterministic topic embedder injected at the cache's embedder extension point, because
``HashEmbedder`` derives vectors from the full normalized text (any exact-miss query is
cosine-uncorrelated with every stored row, so its semantic layer cannot fire by design).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import tempfile
import time
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
from benchmark.stats import (
    Summary,
    abba_schedule,
    block_deltas,
    paired_verdict,
    summarize,
)

_SIZES = (100, 1_000, 10_000)
_WARMUP = 5
_SAMPLES = 50
_BLOCKS = 12
_BATCH_SIZE = 32
_DIM = 32
_QUERY_LRU_ROWS = 256  # SemanticCache._QUERY_EMBEDDING_ROWS; query pools must exceed it


def _pool_size(entries: int, blocks: int, batch_size: int) -> int:
    """Return the query-pool length that defeats the embedding LRU and feeds the ABBA."""
    return max(4 * _QUERY_LRU_ROWS, entries, 4 * blocks * batch_size)


class TopicEmbedder:
    """Deterministic embedder keyed on the first whitespace token (the "topic").

    Texts sharing a topic get identical unit vectors (cosine 1.0), so a reworded query
    is a guaranteed semantic hit, and an unseen topic is a guaranteed miss. The
    ``query`` flag is accepted and ignored, mirroring the ``Embedder`` protocol.
    """

    def __init__(self, dim: int = _DIM) -> None:
        """Configure the embedder's dimension."""
        self.dim = dim

    def embed(self, texts: list[str], *, query: bool = False) -> np.ndarray:
        """Embed ``texts`` into one seeded unit-vector row per text."""
        prepared = [str(text).strip().lower() for text in texts]
        if not prepared:
            return np.zeros((0, self.dim), dtype=np.float32)
        out = np.empty((len(prepared), self.dim), dtype=np.float32)
        for i, text in enumerate(prepared):
            words = text.split()
            topic = words[0] if words else ""
            digest = hashlib.sha256(topic.encode()).digest()
            rng = np.random.default_rng(int.from_bytes(digest[:8], "little"))
            vector = rng.standard_normal(self.dim).astype(np.float32)
            out[i] = vector / np.linalg.norm(vector)
        return out


def _stored_texts(entries: int) -> list[str]:
    """Return ``entries`` deterministic stored texts, each a unique topic."""
    return [f"topic-{i:07d} body {i} memo" for i in range(entries)]


def _semantic_queries(count: int, entries: int) -> list[str]:
    """Return distinct reworded queries that exact-miss but hit stored topics.

    Texts are unique per index (so the embedding LRU never warms) while the leading
    topic cycles over the stored range (so the semantic layer always matches).
    """
    return [f"topic-{i % entries:07d} reworded lookup {i}" for i in range(count)]


def _miss_queries(count: int, offset: int = 1_000_000) -> list[str]:
    """Return distinct queries whose topics match nothing in the cache."""
    return [f"topic-{offset + i:07d} unrelated needle {i}" for i in range(count)]


def _open_cache(directory: Path, entries: int) -> tuple[Any, list[str]]:
    """Build a cache preloaded with ``entries`` stored texts; return it with the texts."""
    from swarm_sdk.retrieval.cache import SemanticCache

    directory.mkdir(parents=True, exist_ok=True)

    cache = SemanticCache(
        str(directory / "cache.db"),
        TopicEmbedder(),
        max_entries=entries * 2,
        max_semantic_rows=entries * 2,
    )
    texts = _stored_texts(entries)
    for i, text in enumerate(texts):
        cache.store(text, f"response-{i}")
    return cache, texts


def _verify_paths(cache: Any, texts: Sequence[str]) -> None:
    """Assert every measured path returns the right answer before any timing."""
    exact = cache.lookup(texts[0])
    assert exact == "response-0", f"exact hit returned {exact!r}"
    semantic = cache.lookup(_semantic_queries(1, len(texts))[0])
    assert semantic == "response-0", f"semantic hit returned {semantic!r}"
    miss = cache.lookup(_miss_queries(1)[0])
    assert miss is None, f"miss returned {miss!r}"
    stats = cache.stats()
    assert stats["exact_hits"] >= 1 and stats["semantic_hits"] >= 1 and stats["misses"] >= 1


def _timed_us(fn: Any) -> float:
    """Return one measurement of ``fn`` in microseconds."""
    start = time.perf_counter_ns()
    fn()
    return (time.perf_counter_ns() - start) / 1e3


def _measure_path(cache: Any, queries: Sequence[str], warmup: int, samples: int) -> Summary:
    """Summarize ``warmup + samples`` lookups rotating over ``queries``.

    The pool is at least four times the cache's 256-row query-embedding LRU, so every
    timed lookup pays the real embed + scan path instead of a warm vector.
    """
    assert len(queries) >= 4 * _QUERY_LRU_ROWS, "query pool must exceed the embedding LRU"
    cursor = 0

    def next_lookup() -> None:
        nonlocal cursor
        cache.lookup(queries[cursor % len(queries)])
        cursor += 1

    for _ in range(warmup):
        next_lookup()
    return summarize([_timed_us(next_lookup) for _ in range(samples)])


def _abba_batch_vs_single(
    cache: Any, queries: Sequence[str], blocks: int, batch_size: int
) -> dict[str, Any]:
    """Compare ``lookup_batch`` (B) against ``batch_size`` single lookups (A), ABBA.

    Each of the ``4 * blocks`` slots uses a fresh window of ``batch_size`` distinct
    queries, so both variants embed the same texts and face comparable LRU state.
    Returns per-variant summaries plus the paired verdict on per-slot milliseconds.
    """
    assert len(queries) >= 4 * blocks * batch_size, "query pool must cover every slot"
    records: list[tuple[str, float]] = []
    cursor = 0

    def window() -> list[str]:
        nonlocal cursor
        picked = [queries[(cursor + i) % len(queries)] for i in range(batch_size)]
        cursor += batch_size
        return picked

    for variant in abba_schedule(blocks):
        picked = window()
        if variant == "A":

            def run_single(picked: list[str] = picked) -> None:
                for text in picked:
                    cache.lookup(text)

            elapsed = _timed_us(run_single)
        else:

            def run_batch(picked: list[str] = picked) -> None:
                cache.lookup_batch(picked)

            elapsed = _timed_us(run_batch)
        records.append((variant, elapsed / 1e3))

    deltas = block_deltas(records)
    verdict = paired_verdict(deltas)
    a_summary = summarize([value for variant, value in records if variant == "A"])
    b_summary = summarize([value for variant, value in records if variant == "B"])
    return {
        "single_lookup_slot_ms": asdict(a_summary),
        "lookup_batch_slot_ms": asdict(b_summary),
        "batch_size": batch_size,
        "single_median_per_query_us": a_summary.median * 1e3 / batch_size,
        "batch_median_per_query_us": b_summary.median * 1e3 / batch_size,
        "verdict": {
            "label": verdict.label,
            "median_delta_ms": verdict.median_delta,
            "noise_floor_ms": verdict.noise_floor,
            "bootstrap_ci_ms": [verdict.ci_low, verdict.ci_high],
        },
    }


def run(
    sizes: tuple[int, ...] = _SIZES,
    *,
    warmup: int = _WARMUP,
    samples: int = _SAMPLES,
    blocks: int = _BLOCKS,
    batch_size: int = _BATCH_SIZE,
) -> dict[str, Any]:
    """Run the full latency report; every number is measured, none hardcoded."""
    per_size: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="swarm-cache-lookup-") as directory:
        root = Path(directory)
        for entries in sizes:
            cache, texts = _open_cache(root / f"cache-{entries}", entries)
            _verify_paths(cache, texts)
            needed = _pool_size(entries, blocks, batch_size)
            exact_pool = (texts * (needed // entries + 1))[:needed]
            semantic_pool = _semantic_queries(needed, entries)
            miss_pool = _miss_queries(needed)
            measurements = {
                path: asdict(_measure_path(cache, pool, warmup, samples))
                for path, pool in (
                    ("exact_hit_us", exact_pool),
                    ("semantic_hit_us", semantic_pool),
                    ("miss_us", miss_pool),
                )
            }
            per_size.append(
                {
                    "entries": entries,
                    **measurements,
                    "batch_vs_single": _abba_batch_vs_single(
                        cache, semantic_pool, blocks, batch_size
                    ),
                }
            )
    return {
        "metadata": {
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "embedder": f"topic-hash dim-{_DIM} (synthetic, deterministic)",
            "query_embedding_lru_rows": _QUERY_LRU_ROWS,
            "query_pool_note": "pools rotate beyond the LRU so every lookup embeds",
            "sizes": list(sizes),
            "warmup": warmup,
            "samples": samples,
            "abba_blocks": blocks,
            "batch_size": batch_size,
        },
        "results": per_size,
    }


def main(argv: list[str] | None = None) -> int:
    """Print the report (and optionally write it under the gitignored results/ tree)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+", default=list(_SIZES))
    parser.add_argument("--samples", type=int, default=_SAMPLES)
    parser.add_argument("--warmup", type=int, default=_WARMUP)
    parser.add_argument("--blocks", type=int, default=_BLOCKS)
    parser.add_argument("--batch-size", type=int, default=_BATCH_SIZE)
    parser.add_argument("--quick", action="store_true", help="smoke workload for tests/CI")
    parser.add_argument("--write-results", action="store_true")
    args = parser.parse_args(argv)
    if args.quick:
        sizes, samples, blocks, batch_size = (100,), 20, 4, 8
    else:
        sizes, samples, blocks, batch_size = (
            tuple(args.sizes),
            args.samples,
            args.blocks,
            args.batch_size,
        )
    report = run(sizes, samples=samples, blocks=blocks, batch_size=batch_size)
    output = json.dumps(report, indent=2)
    if args.write_results:
        path = Path(__file__).resolve().parents[2] / "results" / "cache_lookup_latency"
        path.mkdir(parents=True, exist_ok=True)
        target = path / "latest.json"
        target.write_text(output + "\n", encoding="utf-8")
        print(f"Wrote {target}")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
