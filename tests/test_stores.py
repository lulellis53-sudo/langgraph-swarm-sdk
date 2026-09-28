import numpy as np
import pytest

from swarm_sdk.memory.base import MemoryStore


def _roundtrip(store: MemoryStore) -> None:
    for index, label in enumerate(["alpha", "beta", "gamma"]):
        vector = np.zeros(8, dtype=np.float32)
        vector[index] = 1.0
        store.add(label, vector)
    query = np.zeros(8, dtype=np.float32)
    query[1] = 1.0
    hits = store.search(query, 1)
    assert hits[0].text == "beta"


def test_faiss_roundtrip() -> None:
    pytest.importorskip("faiss")
    from swarm_sdk.memory.faiss_store import FaissStore

    store = FaissStore(8)
    assert store.device == "cpu"
    _roundtrip(store)


def test_faiss_gpu_request_falls_back_without_cuda() -> None:
    pytest.importorskip("faiss")
    from swarm_sdk.memory.faiss_store import FaissStore

    store = FaissStore(8, gpu=True)
    assert store.device in {"cpu", "cuda"}
    _roundtrip(store)


def test_qdrant_roundtrip() -> None:
    pytest.importorskip("qdrant_client")
    from swarm_sdk.memory.qdrant_store import QdrantStore

    _roundtrip(QdrantStore(":memory:", 8))


def test_qdrant_int8_roundtrip() -> None:
    pytest.importorskip("qdrant_client")
    from swarm_sdk.memory.qdrant_store import QdrantStore

    store = QdrantStore(":memory:", 8, quantization="int8")
    assert store.quantization == "int8"
    _roundtrip(store)
