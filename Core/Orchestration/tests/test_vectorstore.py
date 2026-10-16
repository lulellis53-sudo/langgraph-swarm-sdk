"""One shared index, one block of ids per agent."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from orchestration.vectorstore import SharedVectorStore

DIM = 4


def vec(*values: float) -> np.ndarray:
    row = np.array(values, dtype=np.float32)
    return row / np.linalg.norm(row)


@pytest.fixture
def store() -> SharedVectorStore:
    s = SharedVectorStore(dim=DIM)
    s.add("Coder", "Coder/AGENTS.md", 0, "write code", vec(1, 0, 0, 0))
    s.add("Coder", "Coder/AGENTS.md", 1, "run tests", vec(0.9, 0.1, 0, 0))
    s.add("RAG", "RAG/AGENTS.md", 0, "retrieve", vec(0, 1, 0, 0))
    return s


def test_each_agent_gets_its_own_id_block(store: SharedVectorStore) -> None:
    assert store.agents() == {"Coder": 0, "RAG": 1}
    ids = {h.id for h in store.search(vec(1, 1, 0, 0), k=3)}
    assert {i >> 40 for i in ids} == {0, 1}
    assert store.count() == 3
    assert store.count("Coder") == 2


def test_search_without_agent_spans_all_agents(store: SharedVectorStore) -> None:
    hits = store.search(vec(0, 1, 0, 0), k=3)
    assert hits[0].agent == "RAG"
    assert {h.agent for h in hits} == {"Coder", "RAG"}


def test_search_with_agent_returns_only_that_agent(store: SharedVectorStore) -> None:
    hits = store.search(vec(0, 1, 0, 0), k=3, agent="Coder")
    assert hits and {h.agent for h in hits} == {"Coder"}


def test_unknown_agent_returns_empty_not_other_agents(store: SharedVectorStore) -> None:
    assert store.search(vec(1, 0, 0, 0), k=3, agent="Nobody") == []


def test_same_text_in_two_agents_is_kept_twice() -> None:
    s = SharedVectorStore(dim=DIM)
    a = s.add("A", "A/x.md", 0, "shared", vec(1, 0, 0, 0))
    b = s.add("B", "B/x.md", 0, "shared", vec(1, 0, 0, 0))
    assert a != b and s.count() == 2
    assert [h.agent for h in s.search(vec(1, 0, 0, 0), k=5, agent="B")] == ["B"]


def test_k_larger_than_size_and_k_zero(store: SharedVectorStore) -> None:
    assert len(store.search(vec(1, 0, 0, 0), k=50)) == 3
    assert store.search(vec(1, 0, 0, 0), k=0) == []


def test_search_on_empty_store_returns_empty() -> None:
    assert SharedVectorStore(dim=DIM).search(vec(1, 0, 0, 0), k=3) == []


def test_wrong_dimension_raises_value_error(store: SharedVectorStore) -> None:
    with pytest.raises(ValueError, match="dim"):
        store.add("Coder", "s", 9, "t", np.ones(7, dtype=np.float32))
    with pytest.raises(ValueError, match="dim"):
        store.search(np.ones(7, dtype=np.float32), k=1)


def test_has_text_is_per_agent(store: SharedVectorStore) -> None:
    assert store.has_text("Coder", "write code")
    assert not store.has_text("RAG", "write code")


def test_save_and_load_round_trip_keeps_positions(store: SharedVectorStore, tmp_path: Path) -> None:
    store.save(tmp_path / "idx")
    loaded = SharedVectorStore.load(tmp_path / "idx")
    assert loaded.agents() == store.agents()
    assert loaded.count("Coder") == 2
    before = [(h.id, h.agent, h.text) for h in store.search(vec(1, 0, 0, 0), k=3)]
    after = [(h.id, h.agent, h.text) for h in loaded.search(vec(1, 0, 0, 0), k=3)]
    assert before == after
    assert loaded.has_text("RAG", "retrieve")


def test_add_after_load_continues_the_agent_block(store: SharedVectorStore, tmp_path: Path) -> None:
    store.save(tmp_path / "idx")
    loaded = SharedVectorStore.load(tmp_path / "idx")
    assert loaded.add("Coder", "Coder/AGENTS.md", 2, "third", vec(0, 0, 1, 0)) == 2


def test_load_missing_directory_raises_value_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="index"):
        SharedVectorStore.load(tmp_path / "nope")


def test_load_with_mismatched_dim_raises_value_error(
    store: SharedVectorStore, tmp_path: Path
) -> None:
    store.save(tmp_path / "idx")
    meta = tmp_path / "idx" / "slots.json"
    data = json.loads(meta.read_text(encoding="utf-8"))
    data["dim"] = 99
    meta.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="dim"):
        SharedVectorStore.load(tmp_path / "idx")
