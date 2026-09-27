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

    _roundtrip(FaissStore(8))


def test_qdrant_roundtrip() -> None:
    pytest.importorskip("qdrant_client")
    from swarm_sdk.memory.qdrant_store import QdrantStore

    _roundtrip(QdrantStore(":memory:", 8))
