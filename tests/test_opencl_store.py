"""Tests for the OpenCL-backed vector store (uses NumPy fallback without pyopencl)."""

from __future__ import annotations

import numpy as np
import pytest

from swarm_sdk.embeddings import unit
from swarm_sdk.memory.opencl_store import OpenClVecStore


def _one_hot(dim: int, index: int) -> np.ndarray:
    v = np.zeros(dim, dtype=np.float32)
    v[index] = 1.0
    return v


def test_opencl_store_roundtrip(tmp_path):
    store = OpenClVecStore(dim=8)
    labels = ["alpha", "beta", "gamma"]
    for index, label in enumerate(labels):
        store.add(label, _one_hot(8, index))

    query = _one_hot(8, 1)
    hits = store.search(query, 2)
    assert len(hits) == 2
    assert hits[0].text == "beta"
    assert hits[0].id == 1
    assert pytest.approx(hits[0].score, rel=1e-5) == 1.0


def test_opencl_store_empty_search():
    store = OpenClVecStore(dim=8)
    hits = store.search(_one_hot(8, 0), 5)
    assert hits == []


def test_opencl_store_k_clamping():
    store = OpenClVecStore(dim=4)
    store.add("only", _one_hot(4, 0))
    hits = store.search(_one_hot(4, 0), 10)
    assert len(hits) == 1


def test_opencl_store_wrong_dimension():
    store = OpenClVecStore(dim=8)
    with pytest.raises(ValueError):
        store.add("bad", _one_hot(4, 0))
    store.add("ok", _one_hot(8, 0))
    with pytest.raises(ValueError):
        store.search(_one_hot(4, 0), 1)


def test_opencl_store_normalizes_input():
    store = OpenClVecStore(dim=3)
    raw = np.array([2.0, 0.0, 0.0], dtype=np.float32)
    store.add("scaled", raw)
    hits = store.search(unit(raw), 1)
    assert len(hits) == 1
    assert hits[0].text == "scaled"
    assert pytest.approx(hits[0].score, rel=1e-5) == 1.0
