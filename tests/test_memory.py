"""Vector memory stores, hybrid retrieval, and embedding helpers."""

from __future__ import annotations

from pathlib import Path

import hypothesis.strategies as st
import numpy as np
import pytest
from hypothesis import given, settings

from swarm_sdk.embeddings import HashEmbedder, dedupe_texts, unit
from swarm_sdk.hybrid import HybridSearchConfig, hybrid_search, rrf_merge, tokenize
from swarm_sdk.memory.base import MemoryHit, MemoryStore
from swarm_sdk.memory.opencl_store import OpenClVecStore
from swarm_sdk.memory.sqlite_vec import SqliteVecStore


def _one_hot(dim: int, index: int) -> np.ndarray:
    vector = np.zeros(dim, dtype=np.float32)
    vector[index] = 1.0
    return vector


def _roundtrip(store: MemoryStore, *, dim: int = 8) -> None:
    for index, label in enumerate(["alpha", "beta", "gamma"]):
        store.add(label, _one_hot(dim, index))
    hits = store.search(_one_hot(dim, 1), 1)
    assert hits[0].text == "beta"


# --- sqlite-vec / OpenCL / optional backends ---------------------------------


def test_sqlite_vec_int8_roundtrip(tmp_path: Path) -> None:
    store = SqliteVecStore(str(tmp_path / "mem.db"), dim=8)
    _roundtrip(store)
    hits = store.search(_one_hot(8, 1), 2)
    assert hits[0].id == 2
    store.close()


def test_opencl_store_roundtrip_and_guards() -> None:
    store = OpenClVecStore(dim=8)
    assert store.search(_one_hot(8, 0), 5) == []
    _roundtrip(store)
    hits = store.search(_one_hot(8, 1), 2)
    assert len(hits) == 2
    assert pytest.approx(hits[0].score, rel=1e-5) == 1.0

    store.add("only", _one_hot(8, 0))
    assert len(store.search(_one_hot(8, 0), 10)) >= 1

    with pytest.raises(ValueError):
        store.add("bad", _one_hot(4, 0))
    with pytest.raises(ValueError):
        store.search(_one_hot(4, 0), 1)

    scaled = OpenClVecStore(dim=3)
    raw = np.array([2.0, 0.0, 0.0], dtype=np.float32)
    scaled.add("scaled", raw)
    hits = scaled.search(unit(raw), 1)
    assert hits[0].text == "scaled"
    assert pytest.approx(hits[0].score, rel=1e-5) == 1.0


def test_faiss_roundtrip() -> None:
    pytest.importorskip("faiss")
    from swarm_sdk.memory.faiss_store import FaissStore

    store = FaissStore(8)
    assert store.device == "cpu"
    _roundtrip(store)

    gpu = FaissStore(8, gpu=True)
    assert gpu.device in {"cpu", "cuda"}
    _roundtrip(gpu)


def test_qdrant_roundtrip() -> None:
    pytest.importorskip("qdrant_client")
    from swarm_sdk.memory.qdrant_store import QdrantStore

    _roundtrip(QdrantStore(":memory:", 8))
    quantized = QdrantStore(":memory:", 8, quantization="int8")
    assert quantized.quantization == "int8"
    _roundtrip(quantized)


# --- hybrid / tokenize / RRF -------------------------------------------------


class MemoryStub:
    def __init__(self, hits: list[MemoryHit]) -> None:
        self._hits = hits

    def add(self, text: str, vector: np.ndarray) -> int:
        del text, vector
        return 0

    def search(self, vector: np.ndarray, k: int) -> list[MemoryHit]:
        del vector
        return self._hits[:k]


@given(text=st.text(max_size=80))
@settings(max_examples=40)
def test_tokenize_is_lowercase_alnum_tokens(text: str) -> None:
    tokens = tokenize(text)
    assert all(t == t.lower() and t.isalnum() for t in tokens)
    assert "".join(tokens) == "".join(tokenize("".join(tokens)))


@given(
    rankings=st.lists(
        st.lists(st.integers(min_value=0, max_value=31), unique=True, max_size=12),
        min_size=1,
        max_size=4,
    ),
    k=st.integers(min_value=1, max_value=60),
)
@settings(max_examples=50)
def test_rrf_merge_preserves_candidates_and_length(rankings: list[list[int]], k: int) -> None:
    order = rrf_merge(rankings, k=k)
    seen = {idx for ranking in rankings for idx in ranking}
    assert set(order) == seen
    assert len(order) == len(seen)
    assert len(order) == len(set(order))


def test_rrf_merge_orders_overlap() -> None:
    order = rrf_merge([[0, 1, 2], [2, 0, 1]], k=60)
    assert order[0] in {0, 2}


def test_hybrid_search_prefers_keyword_match() -> None:
    hits = [
        MemoryHit(id=1, text="alpha beta", score=0.9),
        MemoryHit(id=2, text="gamma sqlite vec int8", score=0.5),
    ]
    store = MemoryStub(hits)
    embedder = HashEmbedder(16, model_name="bge")
    vector = embedder.embed(["sqlite memory"], query=True)[0]
    cfg = HybridSearchConfig(enabled=True, dense_weight=0.5, keyword_weight=2.0, final_k=2)
    merged = hybrid_search("sqlite int8", store, vector, retrieve_k=2, config=cfg)
    assert merged
    assert any("sqlite" in hit.text for hit in merged)


# --- embeddings helpers ------------------------------------------------------


def test_dedupe_drops_near_duplicates() -> None:
    embedder = HashEmbedder(dim=32)
    texts = ["alpha bravo", "alpha bravo", "totally different phrase"]
    vectors = embedder.embed(texts)
    kept = dedupe_texts(texts, vectors, threshold=0.98)
    assert kept == ["alpha bravo", "totally different phrase"]
    assert float(np.dot(unit(vectors[0]), unit(vectors[1]))) > 0.98


@given(
    texts=st.lists(st.text(min_size=1, max_size=24), min_size=1, max_size=8),
    threshold=st.floats(min_value=0.5, max_value=1.0, allow_nan=False),
)
@settings(max_examples=30)
def test_dedupe_never_grows_and_keeps_order(texts: list[str], threshold: float) -> None:
    embedder = HashEmbedder(dim=16)
    vectors = embedder.embed(texts)
    kept = dedupe_texts(texts, vectors, threshold=threshold)
    assert len(kept) <= len(texts)
    assert kept == [t for t in texts if t in kept]
    # relative order preserved
    positions = {t: i for i, t in enumerate(texts)}
    assert kept == sorted(kept, key=lambda t: positions[t])
