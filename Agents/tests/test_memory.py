"""Vector memory stores, hybrid retrieval, and embedding helpers."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import cast

import hypothesis.strategies as st
import numpy as np
import pytest
from hypothesis import given, settings

from swarm_sdk.memory.base import MemoryHit, MemoryStore
from swarm_sdk.memory.opencl_store import OpenClVecStore, Quantize
from swarm_sdk.retrieval.embeddings import HashEmbedder, dedupe_texts, unit
from swarm_sdk.retrieval.hybrid import HybridSearchConfig, hybrid_search, rrf_merge
from swarm_sdk.retrieval.text import tokenize


def _sqlite_vec_available() -> bool:
    try:
        import sqlite3

        conn = sqlite3.connect(":memory:")
        return hasattr(conn, "enable_load_extension")
    except Exception:
        return False


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
    if not _sqlite_vec_available():
        pytest.skip("sqlite3 build lacks enable_load_extension")
    pytest.importorskip("sqlite_vec")
    from swarm_sdk.memory.sqlite_vec import SqliteVecStore

    store = SqliteVecStore(str(tmp_path / "mem.db"), dim=8)
    _roundtrip(store)
    hits = store.search(_one_hot(8, 1), 2)
    assert hits[0].id == 2
    store.close()


def test_sqlite_int8_fallback_when_extension_loading_is_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "sqlite_vec", None)
    from swarm_sdk.memory.sqlite_vec import SqliteVecStore

    store = SqliteVecStore(str(tmp_path / "fallback.db"), dim=8)
    assert not store._sqlite_vec
    _roundtrip(store)
    hits = store.search(_one_hot(8, 1), 2)
    assert hits[0].text == "beta"
    assert hits[0].id == 2
    keyword_hits = store.keyword_search("beta", 2)
    assert keyword_hits[0].text == "beta"
    store.close()

    reopened = SqliteVecStore(str(tmp_path / "fallback.db"), dim=8)
    assert reopened.search(_one_hot(8, 1), 1)[0].text == "beta"
    reopened.close()


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


def test_opencl_store_bounds_resident_vectors_and_preserves_ids() -> None:
    store = OpenClVecStore(dim=8, max_vectors=2, chunk_rows=1)
    assert store.resident_bytes == 0
    for index, label in enumerate(("first", "second", "third")):
        store.add(label, _one_hot(8, index))

    hits = store.search(_one_hot(8, 2), 2)
    assert [hit.text for hit in hits] == ["third", "second"]
    assert [hit.id for hit in hits] == [2, 1]
    assert store.resident_bytes == 2 * 8 * np.dtype(np.float32).itemsize


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


class FakeMem0:
    """In-memory stand-in for ``mem0.MemoryClient`` (no network)."""

    def __init__(self) -> None:
        self.added: list[dict[str, object]] = []
        self.memories: list[dict[str, object]] = []

    def add(self, messages: object, **kwargs: object) -> object:
        content = ""
        if isinstance(messages, list) and messages:
            first = messages[0]
            if isinstance(first, dict):
                raw = first.get("content", "")
                content = raw if isinstance(raw, str) else str(raw)
        item = {"id": str(len(self.memories) + 1), "memory": content, "score": 0.91}
        self.memories.append(cast(dict[str, object], item))
        self.added.append({"messages": messages, **kwargs})
        return {"results": [item]}

    def search(self, query: str, **kwargs: object) -> object:
        del query
        top_k = kwargs.get("top_k", 10)
        limit = int(top_k) if isinstance(top_k, int) else 10
        return {"results": self.memories[:limit]}


def test_mem0_store_add_and_search_text() -> None:
    from swarm_sdk.memory.mem0_store import Mem0Store

    fake = FakeMem0()
    store = Mem0Store(fake, user_id="alice", agent_id="coder", infer=False)
    row_id = store.add("Q: hike?\nA: weekends", np.zeros(4, dtype=np.float32))
    assert row_id == 1
    assert fake.added[0]["user_id"] == "alice"
    assert fake.added[0]["infer"] is False
    assert store.search(np.zeros(4, dtype=np.float32), 3) == []
    hits = store.search_text("hike", 5)
    assert hits[0].text == "Q: hike?\nA: weekends"
    assert hits[0].score == pytest.approx(0.91)


def test_mem0_from_settings_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from swarm_sdk.config.settings import Settings
    from swarm_sdk.memory.mem0_store import Mem0Store

    monkeypatch.delenv("MEM0_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="MEM0_API_KEY"):
        Mem0Store.from_settings(Settings(memory_backend="mem0"))


def test_recall_texts_uses_search_text() -> None:
    from swarm_sdk.memory.mem0_store import Mem0Store
    from swarm_sdk.retrieval.recall import recall_texts
    from swarm_sdk.retrieval.rerank import KeywordReranker

    fake = FakeMem0()
    store = Mem0Store(fake)
    store.add("Alice hikes on weekends", np.zeros(8, dtype=np.float32))
    texts = recall_texts(
        "hikes",
        store,
        HashEmbedder(8),
        KeywordReranker(),
        retrieve_k=4,
        rerank_k=2,
        dedup_threshold=0.98,
        hybrid_enabled=True,
    )
    assert texts
    assert "hikes" in texts[0]


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
    assert tokenize(" ".join(tokens)) == tokens


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
    # kept is a subsequence of texts (relative order preserved)
    cursor = 0
    for item in kept:
        while cursor < len(texts) and texts[cursor] != item:
            cursor += 1
        assert cursor < len(texts)
        cursor += 1


def test_sqlite_store_uses_wal(tmp_path: Path) -> None:
    from swarm_sdk.memory.sqlite_vec import SqliteVecStore

    store = SqliteVecStore(str(tmp_path / "m.db"), 8)
    mode = store._conn.execute("PRAGMA journal_mode").fetchone()[0]
    store.close()
    assert mode.lower() == "wal"


@pytest.mark.parametrize("mode", ["none", "int8", "binary"])
def test_quantized_store_finds_exact_neighbor(mode: str) -> None:
    store = OpenClVecStore(dim=64, quantize=cast(Quantize, mode))
    rng = np.random.default_rng(1)
    vectors = rng.standard_normal((50, 64)).astype(np.float32)
    for i, v in enumerate(vectors):
        store.add(f"t{i}", np.asarray(v, dtype=np.float32))
    hit = store.search(vectors[7], 1)[0]
    assert hit.text == "t7"
    assert hit.score == pytest.approx(1.0, abs=0.02)


def test_quantized_store_uses_less_memory() -> None:
    def filled(mode: str) -> int:
        s = OpenClVecStore(dim=256, quantize=cast(Quantize, mode))
        for i in range(64):
            s.add(str(i), np.random.default_rng(i).standard_normal(256).astype(np.float32))
        return s.resident_bytes

    none, int8, binary = filled("none"), filled("int8"), filled("binary")
    assert int8 < none / 3
    assert binary < int8 / 4


def test_binary_store_ring_buffer_keeps_ids_and_texts_aligned() -> None:
    store = OpenClVecStore(dim=32, max_vectors=3, chunk_rows=1, quantize="binary")
    rng = np.random.default_rng(5)
    vecs = [rng.standard_normal(32).astype(np.float32) for _ in range(5)]
    ids = [store.add(f"t{i}", v) for i, v in enumerate(vecs)]
    hit = store.search(vecs[4], 1)[0]
    assert hit.text == "t4"
    assert hit.id == ids[4]


def test_store_rejects_unknown_quantize_mode() -> None:
    with pytest.raises(ValueError):
        OpenClVecStore(dim=4, quantize=cast(Quantize, "fp4"))
