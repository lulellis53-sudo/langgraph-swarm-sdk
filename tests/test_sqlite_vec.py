from pathlib import Path

import numpy as np

from swarm_sdk.embeddings import HashEmbedder, dedupe_texts, unit
from swarm_sdk.memory.sqlite_vec import SqliteVecStore


def test_sqlite_vec_int8_roundtrip(tmp_path: Path) -> None:
    store = SqliteVecStore(str(tmp_path / "mem.db"), dim=8)
    labels = ["alpha", "beta", "gamma"]
    for index, label in enumerate(labels):
        vector = np.zeros(8, dtype=np.float32)
        vector[index] = 1.0
        store.add(label, vector)
    query = np.zeros(8, dtype=np.float32)
    query[1] = 1.0
    hits = store.search(query, 2)
    assert hits[0].text == "beta"
    assert hits[0].id == 2
    store.close()


def test_dedupe_drops_near_duplicates() -> None:
    embedder = HashEmbedder(dim=32)
    texts = ["alpha bravo", "alpha bravo", "totally different phrase"]
    vectors = embedder.embed(texts)
    kept = dedupe_texts(texts, vectors, threshold=0.98)
    assert kept == ["alpha bravo", "totally different phrase"]
    assert float(np.dot(unit(vectors[0]), unit(vectors[1]))) > 0.98
