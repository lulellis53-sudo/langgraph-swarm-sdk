"""Tests for SemanticCache stats, batch lookup, and OpenClVecStore LRU eviction."""

from __future__ import annotations

import numpy as np

from swarm_sdk.memory.opencl_store import OpenClVecStore
from swarm_sdk.retrieval.cache import SemanticCache
from swarm_sdk.retrieval.embeddings import Embedder, unit


class _CharBagEmbedder(Embedder):
    """Deterministic embedder where similar texts get similar vectors."""

    dim: int = 26

    def embed(self, texts: list[str], *, query: bool = False) -> np.ndarray:
        rows = []
        for text in texts:
            vec = np.zeros(self.dim, dtype=np.float32)
            for ch in text.lower():
                if "a" <= ch <= "z":
                    vec[ord(ch) - ord("a")] += 1.0
            rows.append(unit(vec))
        return np.stack(rows)


def _cache(threshold: float = 0.85) -> SemanticCache:
    return SemanticCache(":memory:", _CharBagEmbedder(), threshold=threshold)


def test_cache_tracks_exact_and_semantic_hits() -> None:
    cache = _cache()
    cache.store("hello world", "greeting")
    assert cache.lookup("hello world") == "greeting"
    assert cache.lookup("hello world") == "greeting"
    stats = cache.stats()
    assert stats["exact_hits"] == 2
    assert stats["semantic_hits"] == 0
    assert stats["misses"] == 0


def test_cache_semantic_hit_for_similar_query() -> None:
    cache = _cache()
    cache.store("what is the capital of france", "paris")
    result = cache.lookup("capital of france")
    assert result == "paris"
    stats = cache.stats()
    assert stats["exact_hits"] == 0
    assert stats["semantic_hits"] == 1
    assert stats["misses"] == 0


def test_cache_miss_is_counted() -> None:
    cache = _cache()
    assert cache.lookup("xyz123notfound") is None
    assert cache.stats()["misses"] == 1


def test_cache_batch_lookup_matches_single_lookups() -> None:
    cache = _cache()
    cache.store("alpha", "a")
    cache.store("beta", "b")
    cache.store("gamma", "c")

    texts = ["alpha", "missing", "beta", "gamma", "another missing"]
    batch = cache.lookup_batch(texts)
    single = [cache.lookup(t) for t in texts]
    assert batch == single

    stats = cache.stats()
    total_lookups = len(texts)
    # Batch and single together double-count from the caller's perspective;
    # we only assert the counters are internally consistent.
    assert stats["exact_hits"] + stats["semantic_hits"] + stats["misses"] == total_lookups * 2


def test_opencl_store_lru_keeps_hot_vectors() -> None:
    store = OpenClVecStore(8, max_vectors=4, chunk_rows=4)
    # Add four orthogonal one-hot vectors.
    for i in range(4):
        row = np.zeros(8, dtype=np.float32)
        row[i] = 1.0
        store.add(f"v{i}", row)

    # Access v0 and v1 repeatedly to make them hot.
    for _ in range(3):
        store.search(np.eye(8, dtype=np.float32)[0], 1)
        store.search(np.eye(8, dtype=np.float32)[1], 1)

    # Add a new vector; v2 or v3 (the cold ones) should be evicted, not v0/v1.
    new_row = np.zeros(8, dtype=np.float32)
    new_row[7] = 1.0
    store.add("v_hot", new_row)

    # v0 and v1 must still be retrievable.
    for i in (0, 1):
        hits = store.search(np.eye(8, dtype=np.float32)[i], 1)
        assert hits[0].text == f"v{i}"
