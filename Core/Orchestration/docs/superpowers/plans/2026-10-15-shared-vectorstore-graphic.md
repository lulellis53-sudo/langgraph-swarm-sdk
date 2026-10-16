# Shared Vector Store and Graph Graphic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the LangGraph orchestration package with (a) a graph-graphic module that renders any compiled graph to Mermaid files, and (b) an embedding module plus ONE shared FAISS vector store in which every agent folder under `Agents/` owns its own slice of positions (its own RAG), searchable per agent or across all agents.

**Architecture:** One `faiss.IndexIDMap2(IndexFlatIP)` holds all vectors. Each vector gets a 64-bit id in a per-agent block (`agent_slot << 40 | local_index`), so an agent's "position" in the shared index is fixed and recoverable from the id. A JSONL sidecar holds text, agent, source path and chunk number. Search for one agent uses a FAISS `IDSelectorBatch` filter; search across agents passes no filter. The researcher node of the existing graph gets its `SearchFn` from the store.

**Tech Stack:** Python 3.15 (`lazy import`, PEP 810), LangGraph 1.2, langchain-core 1.6, FAISS 1.15.1 (local cp315 wheel, already in the Workspace Pixi env), numpy 2.5, pytest. No new dependencies.

**Spec:** the request "Finalize LangGraph Graphic generation module, Embedding and Vectorstore (all agents together, share same vector, different positions, each subfolder is an agent rag)". Existing code this extends: `orchestration/graph.py`, `docs/superpowers/plans/2026-10-15-langgraph-orchestration.md`. Reference only (do not import): `Core/Websearch/backend/semantic.py` (`Embedder` protocol, `LexicalEmbedder`), `Core/Sdk/swarm_sdk/memory/faiss_store.py`.

## Global Constraints

- Python `>=3.15`; use `lazy import` for `faiss`, `numpy`, `langgraph`, `langchain_core` so `import orchestration.<module>` stays light (`tests/test_lazy_imports.py` pins this).
- Run everything from `/Users/usuario/Desktop/Workspace/Core/Orchestration` as `pixi run python -m pytest -q --tb=short`; the manifest is `/Users/usuario/Desktop/Workspace/pixi.toml`.
- No new dependency. No network at test time. No model download in tests (the offline `HashEmbedder` is the test embedder).
- Google-style docstrings, `X | None`, built-in generics, `logging.getLogger(__name__)`, no `print` in library code.
- Do not follow symlinks while walking `Agents/` (workspace rule: no symlinks).
- Never write secrets or index files into git: the on-disk index lives under `Core/Orchestration/.vectors/` and is gitignored (Task 6).
- Commit only when the user asks, on a feature branch, through the GitKraken MCP with explicit file paths. The "Checkpoint" step in each task is a `git_status` check, not a commit.

## Review Focus

Inputs and conditions the spec implies but the happy-path tests would not hit, most likely first:

1. Empty or whitespace-only query, or `k <= 0`: returns `[]`, never raises. Pinned in Task 3.
2. Search for an agent that has no chunks (or does not exist): returns `[]`, not another agent's hits. Pinned in Task 3.
3. Same text ingested by two agents: both kept, at different ids, and an agent-filtered search returns only its own copy. Pinned in Task 3.
4. Re-ingesting an unchanged folder: no duplicate vectors (idempotent by content hash). Pinned in Task 5.
5. Index saved with one dimension and loaded with an embedder of another: clear `ValueError`, not a FAISS crash. Pinned in Task 4.
6. Agent folders named `_shared` / `_test` / hidden, empty files, non-UTF-8 bytes, `k` larger than the number of vectors. Pinned in Tasks 3 and 5.

## File Structure

| File | Responsibility |
| --- | --- |
| `orchestration/graphic.py` | Render a compiled graph to Mermaid text and write `.mmd` / `.md` files. Nothing else. |
| `orchestration/embedding.py` | `Embedder` protocol, offline `HashEmbedder`, optional `FastEmbedEmbedder`, `default_embedder()`. |
| `orchestration/vectorstore.py` | `SharedVectorStore`: ids per agent slot, add, filtered search, save, load. |
| `orchestration/agent_rag.py` | Walk `Agents/<Name>/`, chunk Markdown, ingest into the store, build a `SearchFn`. |
| `tests/test_graphic.py`, `tests/test_embedding.py`, `tests/test_vectorstore.py`, `tests/test_agent_rag.py`, `tests/test_rag_graph_e2e.py` | One test file per module, plus one end-to-end test. |
| `README.md` | Modify: usage of the three new modules. |
| `.gitignore` | Modify: ignore `.vectors/`. |

Shared names used across tasks (keep exactly):

```python
# embedding.py
class Embedder(Protocol):
    dim: int
    def embed(self, texts: list[str], *, query: bool = False) -> "np.ndarray": ...
# vectorstore.py
@dataclass(frozen=True, slots=True)
class Hit: id: int; agent: str; source: str; chunk: int; text: str; score: float
class SharedVectorStore:
    def __init__(self, dim: int) -> None
    def add(self, agent: str, source: str, chunk: int, text: str, vector: "np.ndarray") -> int
    def search(self, vector: "np.ndarray", k: int = 4, *, agent: str | None = None) -> list[Hit]
    def agents(self) -> dict[str, int]          # agent -> slot
    def count(self, agent: str | None = None) -> int
    def has_text(self, agent: str, text: str) -> bool
    def save(self, directory: Path) -> None
    @classmethod
    def load(cls, directory: Path) -> "SharedVectorStore"
# agent_rag.py
def chunk_markdown(text: str, max_chars: int = 1200) -> list[str]
def ingest_agents(root: Path, store: SharedVectorStore, embedder: Embedder) -> dict[str, int]
def make_search(store: SharedVectorStore, embedder: Embedder, *, agent: str | None = None, k: int = 4) -> SearchFn
# graphic.py
def render_mermaid(graph: object) -> str
def write_graph_files(graph: object, directory: Path, name: str = "graph") -> list[Path]
```

---

### Task 1: Graph graphic module

**Files:**

- Create: `orchestration/graphic.py`
- Test: `tests/test_graphic.py`

**Interfaces:**

- Consumes: a compiled LangGraph graph (anything with `.get_graph().draw_mermaid() -> str`), for example the result of `build_graph(...)`.
- Produces: `render_mermaid(graph) -> str`; `write_graph_files(graph, directory, name="graph") -> list[Path]` writing `<name>.mmd` and `<name>.md` (a fenced ```` ```mermaid ```` block) and returning both paths.
- [ ] **Step 1: Write the failing test**

```python
# tests/test_graphic.py
"""Graph graphic: Mermaid text and files, offline (no mermaid.ink call)."""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from orchestration.graph import build_graph
from orchestration.graphic import render_mermaid, write_graph_files


@pytest.fixture
def compiled():
    return build_graph(FakeListChatModel(responses=["p", "a"]), lambda plan: "n")


def test_render_mermaid_lists_every_node(compiled) -> None:
    text = render_mermaid(compiled)
    assert text.startswith("---") or text.startswith("graph")
    for node in ("planner", "researcher", "writer"):
        assert node in text


def test_write_graph_files_creates_mmd_and_md(compiled, tmp_path: Path) -> None:
    paths = write_graph_files(compiled, tmp_path / "out", name="orch")
    assert [p.name for p in paths] == ["orch.mmd", "orch.md"]
    assert "planner" in paths[0].read_text(encoding="utf-8")
    assert paths[1].read_text(encoding="utf-8").startswith("```mermaid\n")


def test_write_graph_files_rejects_path_in_name(compiled, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="name"):
        write_graph_files(compiled, tmp_path, name="../evil")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pixi run python -m pytest tests/test_graphic.py -q --tb=short`
Expected: FAIL with `ModuleNotFoundError: No module named 'orchestration.graphic'`.

- [ ] **Step 3: Write minimal implementation**

```python
# orchestration/graphic.py
"""Render a compiled LangGraph graph to Mermaid text and files (offline)."""

from __future__ import annotations

lazy from pathlib import Path

__all__ = ["render_mermaid", "write_graph_files"]


def render_mermaid(graph: object) -> str:
    """Return the Mermaid source of a compiled graph.

    Args:
        graph: A compiled LangGraph graph exposing ``get_graph()``.

    Returns:
        Mermaid flowchart text. No network call is made (PNG rendering via
        mermaid.ink is deliberately not used).
    """
    return graph.get_graph().draw_mermaid()


def write_graph_files(graph: object, directory: Path, name: str = "graph") -> list[Path]:
    """Write ``<name>.mmd`` and a Markdown wrapper ``<name>.md``.

    Args:
        graph: A compiled LangGraph graph.
        directory: Output folder; created if missing.
        name: File stem. Must not contain a path separator.

    Returns:
        ``[<name>.mmd, <name>.md]`` as paths.

    Raises:
        ValueError: If ``name`` is empty or contains a path separator.
    """
    if not name or Path(name).name != name or name in {".", ".."}:
        raise ValueError(f"name must be a plain file stem, got {name!r}")
    text = render_mermaid(graph)
    directory.mkdir(parents=True, exist_ok=True)
    mmd = directory / f"{name}.mmd"
    md = directory / f"{name}.md"
    mmd.write_text(text, encoding="utf-8")
    md.write_text(f"```mermaid\n{text}\n```\n", encoding="utf-8")
    return [mmd, md]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pixi run python -m pytest tests/test_graphic.py tests/test_lazy_imports.py -q --tb=short`
Expected: PASS (5 passed).

- [ ] **Step 5: Checkpoint**

Run: `pixi run ruff check orchestration/graphic.py tests/test_graphic.py && pixi run ruff format --check orchestration/graphic.py tests/test_graphic.py`; then GitKraken `git_status`. Do not commit unless asked.

---

### Task 2: Embedding module

**Files:**

- Create: `orchestration/embedding.py`
- Test: `tests/test_embedding.py`

**Interfaces:**

- Consumes: nothing from earlier tasks.
- Produces: `Embedder` protocol (`dim: int`, `embed(texts, *, query=False) -> np.ndarray` of shape `(len(texts), dim)`, float32, L2-normalized rows, zero rows stay zero); `HashEmbedder(dim=384)`; `FastEmbedEmbedder(model_name="BAAI/bge-small-en-v1.5", dim=384)` (imports `fastembed` only when constructed); `default_embedder() -> Embedder` (env `ORCHESTRATION_EMBED_BACKEND` = `auto` | `hash` | `fastembed`; `auto` uses fastembed only if importable, else hash).
- [ ] **Step 1: Write the failing test**

```python
# tests/test_embedding.py
"""Embedders: deterministic, normalized, offline by default."""

from __future__ import annotations

import numpy as np
import pytest

from orchestration.embedding import HashEmbedder, default_embedder


def test_hash_embedder_shape_dtype_and_unit_norm() -> None:
    vectors = HashEmbedder(dim=64).embed(["alpha beta", "gamma"])
    assert vectors.shape == (2, 64)
    assert vectors.dtype == np.float32
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5)


def test_hash_embedder_is_deterministic_across_calls() -> None:
    embedder = HashEmbedder(dim=64)
    assert np.array_equal(embedder.embed(["same text"]), embedder.embed(["same text"]))


def test_shared_words_score_higher_than_unrelated_words() -> None:
    embedder = HashEmbedder(dim=256)
    a, b, c = embedder.embed(["faiss vector index", "vector index search", "banana bread recipe"])
    assert float(a @ b) > float(a @ c)


def test_empty_text_gives_zero_row_not_nan() -> None:
    row = HashEmbedder(dim=16).embed([""])[0]
    assert not np.isnan(row).any()
    assert float(np.linalg.norm(row)) == 0.0


def test_hash_embedder_rejects_non_positive_dim() -> None:
    with pytest.raises(ValueError, match="dim"):
        HashEmbedder(dim=0)


def test_default_embedder_honours_hash_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCHESTRATION_EMBED_BACKEND", "hash")
    assert isinstance(default_embedder(), HashEmbedder)


def test_default_embedder_rejects_unknown_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCHESTRATION_EMBED_BACKEND", "nope")
    with pytest.raises(ValueError, match="ORCHESTRATION_EMBED_BACKEND"):
        default_embedder()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pixi run python -m pytest tests/test_embedding.py -q --tb=short`
Expected: FAIL with `ModuleNotFoundError: No module named 'orchestration.embedding'`.

- [ ] **Step 3: Write minimal implementation**

```python
# orchestration/embedding.py
"""Text embedders for the shared agent vector store.

``HashEmbedder`` is offline and deterministic (feature-hashed bag of words): it
measures word overlap, not meaning. ``FastEmbedEmbedder`` gives real dense
vectors when ``fastembed`` is installed (no cp315 ``onnxruntime`` wheel exists
on this Intel Mac, so ``auto`` falls back to hashing here).
"""

from __future__ import annotations

lazy import hashlib
lazy import importlib.util
lazy import os
lazy import re
lazy import numpy as np
lazy from typing import Protocol

__all__ = ["Embedder", "FastEmbedEmbedder", "HashEmbedder", "default_embedder"]

_WORD = re.compile(r"\w+")
DEFAULT_DIM = 384


class Embedder(Protocol):
    """Batch text embedder returning unit-norm float32 rows."""

    dim: int

    def embed(self, texts: list[str], *, query: bool = False) -> np.ndarray:
        """Embed ``texts``; ``query`` selects the query-side representation."""
        ...


class HashEmbedder:
    """Deterministic feature-hashed bag-of-words embedder (blake2b, not ``hash()``)."""

    def __init__(self, dim: int = DEFAULT_DIM) -> None:
        """Create an embedder with ``dim`` hashed features.

        Raises:
            ValueError: If ``dim`` is not positive.
        """
        if dim < 1:
            raise ValueError(f"dim must be positive, got {dim}")
        self.dim = dim

    def embed(self, texts: list[str], *, query: bool = False) -> np.ndarray:
        """Return one L2-normalized row per text; ``query`` is ignored."""
        del query
        rows = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in _WORD.findall(text.casefold()):
                value = int.from_bytes(hashlib.blake2b(word.encode(), digest_size=8).digest(), "little")
                rows[row, value % self.dim] += 1.0 if (value >> 63) & 1 else -1.0
            norm = float(np.linalg.norm(rows[row]))
            if norm:
                rows[row] /= norm
        return rows


class FastEmbedEmbedder:
    """Dense embeddings through ``fastembed`` (imported when constructed)."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5", dim: int = DEFAULT_DIM) -> None:
        """Load the model. Requires ``fastembed``; raises ``ImportError`` if missing."""
        from fastembed import TextEmbedding

        self.dim = dim
        self._model = TextEmbedding(model_name=model_name)

    def embed(self, texts: list[str], *, query: bool = False) -> np.ndarray:
        """Embed and L2-normalize; ``query`` is ignored (bge needs no prefix here)."""
        del query
        rows = np.asarray(list(self._model.embed(texts)), dtype=np.float32).reshape(len(texts), -1)
        norms = np.linalg.norm(rows, axis=1, keepdims=True)
        return rows / np.where(norms == 0, 1.0, norms)


def default_embedder() -> Embedder:
    """Pick an embedder from ``ORCHESTRATION_EMBED_BACKEND`` (auto | hash | fastembed).

    Raises:
        ValueError: If the variable holds any other value.
    """
    backend = os.environ.get("ORCHESTRATION_EMBED_BACKEND", "auto").strip().lower()
    if backend not in {"auto", "hash", "fastembed"}:
        raise ValueError("ORCHESTRATION_EMBED_BACKEND must be auto, hash, or fastembed")
    if backend == "hash" or (backend == "auto" and importlib.util.find_spec("fastembed") is None):
        return HashEmbedder()
    return FastEmbedEmbedder()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pixi run python -m pytest tests/test_embedding.py tests/test_lazy_imports.py -q --tb=short`
Expected: PASS. If `lazy import numpy as np` is rejected by the 3.15 build for the annotation `np.ndarray`, move that one import under `if TYPE_CHECKING:` and keep the runtime `import numpy as np` inside `embed`; do not drop the lazy-import test.

- [ ] **Step 5: Checkpoint**

Run: `pixi run ruff check orchestration/embedding.py tests/test_embedding.py && pixi run ruff format --check orchestration/embedding.py tests/test_embedding.py`; GitKraken `git_status`. Do not commit unless asked.

---

### Task 3: Shared vector store with per-agent positions

**Files:**

- Create: `orchestration/vectorstore.py`
- Test: `tests/test_vectorstore.py`

**Interfaces:**

- Consumes: unit-norm float32 vectors (Task 2 output).
- Produces: `Hit` and `SharedVectorStore` exactly as listed in File Structure. Id layout: `id = (slot << 40) | local`, where `slot` is the agent's order of first appearance (0, 1, 2, ...) and `local` counts that agent's vectors from 0. `agents()` returns `{name: slot}`.
- [ ] **Step 1: Write the failing test**

```python
# tests/test_vectorstore.py
"""One shared index, one block of ids per agent."""

from __future__ import annotations

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


def test_unknown_or_empty_agent_returns_empty_not_other_agents(store: SharedVectorStore) -> None:
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pixi run python -m pytest tests/test_vectorstore.py -q --tb=short`
Expected: FAIL with `ModuleNotFoundError: No module named 'orchestration.vectorstore'`.

- [ ] **Step 3: Write minimal implementation**

```python
# orchestration/vectorstore.py
"""One shared FAISS index; every agent owns a block of ids ("positions").

Id layout: ``id = (slot << 40) | local``. ``slot`` is the agent's order of first
appearance; ``local`` counts that agent's vectors from 0. Vectors are expected
to be L2-normalized, so inner product equals cosine similarity.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

lazy import faiss
lazy import numpy as np

__all__ = ["Hit", "SharedVectorStore"]

_SLOT_SHIFT = 40
_LOCAL_MASK = (1 << _SLOT_SHIFT) - 1


@dataclass(frozen=True, slots=True)
class Hit:
    """One search result.

    Attributes:
        id: Position in the shared index (``slot << 40 | local``).
        agent: Agent folder that owns the chunk.
        source: Path of the source file, relative to the agents root.
        chunk: Chunk number inside that source file.
        text: Chunk text.
        score: Cosine similarity to the query (higher is closer).
    """

    id: int
    agent: str
    source: str
    chunk: int
    text: str
    score: float


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class SharedVectorStore:
    """All agents' vectors in one index, separated by id block and metadata."""

    def __init__(self, dim: int) -> None:
        """Create an empty store for vectors of ``dim`` floats."""
        if dim < 1:
            raise ValueError(f"dim must be positive, got {dim}")
        self.dim = dim
        self._index = faiss.IndexIDMap2(faiss.IndexFlatIP(dim))
        self._slots: dict[str, int] = {}
        self._rows: dict[int, dict[str, object]] = {}
        self._next_local: dict[str, int] = {}
        self._seen: set[tuple[str, str]] = set()

    def agents(self) -> dict[str, int]:
        """Return ``{agent: slot}`` in order of first appearance."""
        return dict(self._slots)

    def count(self, agent: str | None = None) -> int:
        """Count vectors overall, or for one agent."""
        if agent is None:
            return len(self._rows)
        return self._next_local.get(agent, 0)

    def has_text(self, agent: str, text: str) -> bool:
        """Return True if this agent already holds this exact text."""
        return (agent, _digest(text)) in self._seen

    def add(self, agent: str, source: str, chunk: int, text: str, vector: np.ndarray) -> int:
        """Store one chunk and return its id.

        Raises:
            ValueError: If ``vector`` does not have ``dim`` floats.
        """
        row = self._check(vector)
        slot = self._slots.setdefault(agent, len(self._slots))
        local = self._next_local.get(agent, 0)
        self._next_local[agent] = local + 1
        position = (slot << _SLOT_SHIFT) | local
        self._index.add_with_ids(row, np.array([position], dtype=np.int64))
        self._rows[position] = {"agent": agent, "source": source, "chunk": chunk, "text": text}
        self._seen.add((agent, _digest(text)))
        return position

    def search(self, vector: np.ndarray, k: int = 4, *, agent: str | None = None) -> list[Hit]:
        """Return up to ``k`` nearest chunks, optionally restricted to one agent.

        Raises:
            ValueError: If ``vector`` does not have ``dim`` floats.
        """
        row = self._check(vector)
        if k <= 0 or not self._rows:
            return []
        params = None
        if agent is not None:
            ids = [p for p, meta in self._rows.items() if meta["agent"] == agent]
            if not ids:
                return []
            params = faiss.SearchParameters()
            params.sel = faiss.IDSelectorBatch(np.array(ids, dtype=np.int64))
        scores, found = self._index.search(row, min(k, len(self._rows)), params=params)
        hits: list[Hit] = []
        for score, position in zip(scores[0], found[0], strict=True):
            if position < 0:
                continue
            meta = self._rows[int(position)]
            hits.append(
                Hit(
                    id=int(position),
                    agent=str(meta["agent"]),
                    source=str(meta["source"]),
                    chunk=int(meta["chunk"]),  # type: ignore[arg-type]
                    text=str(meta["text"]),
                    score=float(score),
                )
            )
        return hits

    def _check(self, vector: np.ndarray) -> np.ndarray:
        row = np.ascontiguousarray(np.asarray(vector, dtype=np.float32).reshape(1, -1))
        if row.shape[1] != self.dim:
            raise ValueError(f"vector dim {row.shape[1]} does not match store dim {self.dim}")
        return row
```

Note: the `# type: ignore[arg-type]` above is a shortcut; instead type `_rows` as `dict[int, _Row]` with a `TypedDict` (`agent: str`, `source: str`, `chunk: int`, `text: str`) and delete the ignore and the `str(...)` casts. The workspace rules forbid unexplained ignores.

- [ ] **Step 4: Run test to verify it passes**

Run: `pixi run python -m pytest tests/test_vectorstore.py tests/test_lazy_imports.py -q --tb=short`
Expected: PASS (9 + 2). The filtered-search call was verified on the Workspace env: `search(..., params=SearchParameters(sel=IDSelectorBatch(ids)))` on `IndexIDMap2(IndexFlatIP)` returned only selected ids.

- [ ] **Step 5: Checkpoint**

Run: `pixi run ruff check orchestration/vectorstore.py tests/test_vectorstore.py && pixi run ruff format --check orchestration/vectorstore.py tests/test_vectorstore.py`; GitKraken `git_status`. Do not commit unless asked.

---

### Task 4: Persist and reload the shared index

**Files:**

- Modify: `orchestration/vectorstore.py` (add `save`, `load`)
- Test: `tests/test_vectorstore.py` (append)

**Interfaces:**

- Consumes: `SharedVectorStore` from Task 3.
- Produces: `save(directory)` writes `index.faiss` and `meta.jsonl` (one JSON object per vector with `id`, `agent`, `source`, `chunk`, `text`) plus `slots.json` (`{"dim": int, "slots": {agent: slot}}`); `load(directory)` rebuilds an equal store; a missing file or a dim mismatch raises `ValueError`.
- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_vectorstore.py
import json
from pathlib import Path


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
    new_id = loaded.add("Coder", "Coder/AGENTS.md", 2, "third", vec(0, 0, 1, 0))
    assert new_id == (0 << 40) | 2


def test_load_missing_directory_raises_value_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="index"):
        SharedVectorStore.load(tmp_path / "nope")


def test_load_with_mismatched_dim_raises_value_error(store: SharedVectorStore, tmp_path: Path) -> None:
    store.save(tmp_path / "idx")
    meta = tmp_path / "idx" / "slots.json"
    data = json.loads(meta.read_text(encoding="utf-8"))
    data["dim"] = 99
    meta.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="dim"):
        SharedVectorStore.load(tmp_path / "idx")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pixi run python -m pytest tests/test_vectorstore.py -q --tb=short`
Expected: FAIL with `AttributeError: 'SharedVectorStore' object has no attribute 'save'`.

- [ ] **Step 3: Write minimal implementation**

Add `import json` and `from pathlib import Path` at the top of `orchestration/vectorstore.py`, then add these methods to `SharedVectorStore`:

```python
    def save(self, directory: Path) -> None:
        """Write ``index.faiss``, ``meta.jsonl`` and ``slots.json`` into ``directory``."""
        directory.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(directory / "index.faiss"))
        with (directory / "meta.jsonl").open("w", encoding="utf-8") as handle:
            for position, meta in self._rows.items():
                handle.write(json.dumps({"id": position, **meta}, ensure_ascii=False) + "\n")
        (directory / "slots.json").write_text(
            json.dumps({"dim": self.dim, "slots": self._slots}), encoding="utf-8"
        )

    @classmethod
    def load(cls, directory: Path) -> SharedVectorStore:
        """Rebuild a store saved by :meth:`save`.

        Raises:
            ValueError: If a file is missing or the stored dimension disagrees with the index.
        """
        paths = [directory / name for name in ("index.faiss", "meta.jsonl", "slots.json")]
        if not all(p.is_file() for p in paths):
            raise ValueError(f"no saved index in {directory}")
        header = json.loads(paths[2].read_text(encoding="utf-8"))
        index = faiss.read_index(str(paths[0]))
        if index.d != header["dim"]:
            raise ValueError(f"index dim {index.d} does not match slots.json dim {header['dim']}")
        store = cls(header["dim"])
        store._index = index
        store._slots = {str(k): int(v) for k, v in header["slots"].items()}
        for line in paths[1].read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            position = int(row.pop("id"))
            store._rows[position] = row
            agent = row["agent"]
            store._next_local[agent] = max(store._next_local.get(agent, 0), (position & _LOCAL_MASK) + 1)
            store._seen.add((agent, _digest(row["text"])))
        return store
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pixi run python -m pytest tests/test_vectorstore.py -q --tb=short`
Expected: PASS (13 passed).

- [ ] **Step 5: Checkpoint**

Run ruff check and format check on both files; GitKraken `git_status`. Do not commit unless asked.

---

### Task 5: Per-agent folder ingest and search function

**Files:**

- Create: `orchestration/agent_rag.py`
- Test: `tests/test_agent_rag.py`

**Interfaces:**

- Consumes: `Embedder` (Task 2), `SharedVectorStore` and `Hit` (Tasks 3-4), `SearchFn` from `orchestration.graph` (`Callable[[str], str]`).
- Produces: `chunk_markdown(text, max_chars=1200) -> list[str]` (split on Markdown headings, then pack paragraphs up to `max_chars`; a single paragraph longer than `max_chars` is hard-split; blank input gives `[]`); `ingest_agents(root, store, embedder) -> dict[str, int]` (new chunks added per agent; agent = first-level subfolder name; skips names starting with `_` or `.`; walks `*.md` recursively without following symlinks; skips empty files and files that are not valid UTF-8; skips a chunk the agent already holds, so re-running adds 0); `make_search(store, embedder, *, agent=None, k=4) -> SearchFn` (embeds the query with `query=True`, returns hits as lines `[Agent/source#chunk score] text`, joined by newlines; empty query or no hits returns `""`).
- [ ] **Step 1: Write the failing test**

```python
# tests/test_agent_rag.py
"""Each subfolder of the agents root is one agent's RAG inside the shared store."""

from __future__ import annotations

from pathlib import Path

import pytest

from orchestration.agent_rag import chunk_markdown, ingest_agents, make_search
from orchestration.embedding import HashEmbedder
from orchestration.vectorstore import SharedVectorStore


@pytest.fixture
def agents_root(tmp_path: Path) -> Path:
    (tmp_path / "Coder").mkdir()
    (tmp_path / "Coder" / "AGENTS.md").write_text(
        "# Coder\n\nWrite python code and run pytest.\n\n## Style\n\nUse ruff and type hints.\n",
        encoding="utf-8",
    )
    (tmp_path / "RAG").mkdir()
    (tmp_path / "RAG" / "notes").mkdir()
    (tmp_path / "RAG" / "notes" / "faiss.md").write_text(
        "# Retrieval\n\nFAISS vector index with reranking.\n", encoding="utf-8"
    )
    (tmp_path / "_shared").mkdir()
    (tmp_path / "_shared" / "COMMON.md").write_text("# Common\n\nignored shared text\n", encoding="utf-8")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "x.md").write_text("# H\n\nhidden\n", encoding="utf-8")
    return tmp_path


def test_chunk_markdown_splits_on_headings_and_caps_length() -> None:
    chunks = chunk_markdown("# A\n\none\n\n## B\n\ntwo\n", max_chars=1200)
    assert len(chunks) == 2 and chunks[0].startswith("# A") and chunks[1].startswith("## B")
    long = chunk_markdown("x" * 50, max_chars=20)
    assert all(len(c) <= 20 for c in long) and "".join(long) == "x" * 50


def test_chunk_markdown_blank_input_gives_no_chunks() -> None:
    assert chunk_markdown("") == [] and chunk_markdown("  \n\n ") == []


def test_ingest_uses_one_store_one_slot_per_agent_folder(agents_root: Path) -> None:
    store = SharedVectorStore(dim=128)
    added = ingest_agents(agents_root, store, HashEmbedder(dim=128))
    assert set(added) == {"Coder", "RAG"}
    assert set(store.agents()) == {"Coder", "RAG"}
    assert store.count("RAG") == added["RAG"] >= 1


def test_ingest_is_idempotent(agents_root: Path) -> None:
    store = SharedVectorStore(dim=128)
    embedder = HashEmbedder(dim=128)
    ingest_agents(agents_root, store, embedder)
    total = store.count()
    assert sum(ingest_agents(agents_root, store, embedder).values()) == 0
    assert store.count() == total


def test_ingest_skips_empty_and_non_utf8_files(agents_root: Path) -> None:
    (agents_root / "Coder" / "empty.md").write_text("", encoding="utf-8")
    (agents_root / "Coder" / "bad.md").write_bytes(b"\xff\xfe\x00bad")
    store = SharedVectorStore(dim=128)
    ingest_agents(agents_root, store, HashEmbedder(dim=128))
    assert {h.source for h in store.search(HashEmbedder(dim=128).embed(["code"])[0], k=20)} <= {
        "Coder/AGENTS.md",
        "RAG/notes/faiss.md",
    }


def test_ingest_does_not_follow_symlinked_folders(agents_root: Path, tmp_path_factory) -> None:
    outside = tmp_path_factory.mktemp("outside")
    (outside / "secret.md").write_text("# S\n\noutside secret\n", encoding="utf-8")
    (agents_root / "Linked").symlink_to(outside, target_is_directory=True)
    store = SharedVectorStore(dim=128)
    ingest_agents(agents_root, store, HashEmbedder(dim=128))
    assert "Linked" not in store.agents()


def test_make_search_filters_by_agent_and_handles_empty_query(agents_root: Path) -> None:
    store = SharedVectorStore(dim=128)
    embedder = HashEmbedder(dim=128)
    ingest_agents(agents_root, store, embedder)
    only_rag = make_search(store, embedder, agent="RAG", k=3)("faiss vector index")
    assert only_rag.startswith("[RAG/") and "Coder/" not in only_rag
    everyone = make_search(store, embedder, k=5)("python pytest ruff faiss")
    assert "Coder/" in everyone and "RAG/" in everyone
    assert make_search(store, embedder)("   ") == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pixi run python -m pytest tests/test_agent_rag.py -q --tb=short`
Expected: FAIL with `ModuleNotFoundError: No module named 'orchestration.agent_rag'`.

- [ ] **Step 3: Write minimal implementation**

```python
# orchestration/agent_rag.py
"""Ingest ``Agents/<Name>/`` folders into the shared store and search them."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from orchestration.embedding import Embedder
from orchestration.graph import SearchFn
from orchestration.vectorstore import SharedVectorStore

__all__ = ["chunk_markdown", "ingest_agents", "make_search"]

logger = logging.getLogger(__name__)
_HEADING = re.compile(r"(?m)^(?=#{1,6}\s)")


def chunk_markdown(text: str, max_chars: int = 1200) -> list[str]:
    """Split Markdown on headings, pack paragraphs up to ``max_chars``, hard-split the rest.

    Args:
        text: Markdown source.
        max_chars: Maximum characters per chunk (must be positive).

    Returns:
        Non-empty chunks in document order; blank input gives ``[]``.
    """
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    chunks: list[str] = []
    for section in _HEADING.split(text):
        section = section.strip()
        if not section:
            continue
        current = ""
        for paragraph in re.split(r"\n\s*\n", section):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            candidate = f"{current}\n\n{paragraph}" if current else paragraph
            if len(candidate) <= max_chars:
                current = candidate
                continue
            if current:
                chunks.append(current)
            while len(paragraph) > max_chars:
                chunks.append(paragraph[:max_chars])
                paragraph = paragraph[max_chars:]
            current = paragraph
        if current:
            chunks.append(current)
    return chunks


def _markdown_files(folder: Path) -> list[Path]:
    found: list[Path] = []
    for path in sorted(folder.rglob("*.md")):
        if path.is_symlink() or any(part.is_symlink() for part in path.parents if part != folder.parent and folder in (part, *part.parents)):
            continue
        if path.is_file():
            found.append(path)
    return found


def ingest_agents(root: Path, store: SharedVectorStore, embedder: Embedder) -> dict[str, int]:
    """Add every agent folder's Markdown chunks to the one shared store.

    Args:
        root: Folder whose first-level subfolders are agents (for example ``Agents/``).
        store: Shared store; each agent gets its own id block.
        embedder: Must produce vectors of ``store.dim``.

    Returns:
        ``{agent: chunks added this call}``; agents with nothing new are omitted.
    """
    added: dict[str, int] = {}
    for folder in sorted(p for p in root.iterdir() if p.is_dir() and not p.is_symlink()):
        agent = folder.name
        if agent.startswith(("_", ".")):
            continue
        for path in _markdown_files(folder):
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                logger.warning("skipping non-UTF-8 file %s", path)
                continue
            source = path.relative_to(root).as_posix()
            fresh = [
                (number, chunk)
                for number, chunk in enumerate(chunk_markdown(text))
                if not store.has_text(agent, chunk)
            ]
            if not fresh:
                continue
            vectors = embedder.embed([chunk for _, chunk in fresh])
            for (number, chunk), vector in zip(fresh, vectors, strict=True):
                store.add(agent, source, number, chunk, vector)
            added[agent] = added.get(agent, 0) + len(fresh)
    return added


def make_search(
    store: SharedVectorStore, embedder: Embedder, *, agent: str | None = None, k: int = 4
) -> SearchFn:
    """Build the ``SearchFn`` that the graph's researcher node calls.

    Args:
        store: Shared store.
        embedder: Query embedder (same one used for ingest).
        agent: Restrict to this agent's RAG, or ``None`` to search all agents.
        k: Hits to return.

    Returns:
        A function from query text to lines ``[Agent/source#chunk 0.123] text``.
    """

    def search(query: str) -> str:
        if not query.strip():
            return ""
        vector = embedder.embed([query], query=True)[0]
        hits = store.search(vector, k=k, agent=agent)
        return "\n".join(f"[{h.source}#{h.chunk} {h.score:.3f}] {h.text}" for h in hits)

    return search
```

Simplify `_markdown_files` before running: `rglob` does not follow directory symlinks on 3.15, so keep only `if path.is_file() and not path.is_symlink()`. Delete the `parents` expression; it is wrong and unnecessary.

- [ ] **Step 4: Run test to verify it passes**

Run: `pixi run python -m pytest tests/test_agent_rag.py tests/test_lazy_imports.py -q --tb=short`
Expected: PASS. If `test_ingest_does_not_follow_symlinked_folders` fails because `iterdir` yields the link as a directory, the `not p.is_symlink()` guard in `ingest_agents` is what stops it; fix the guard, not the test.

- [ ] **Step 5: Checkpoint**

Run ruff check and format check on both files; GitKraken `git_status`. Do not commit unless asked.

---

### Task 6: End-to-end wiring, docs, gitignore

**Files:**

- Create: `tests/test_rag_graph_e2e.py`
- Modify: `README.md`, `.gitignore`

**Interfaces:**

- Consumes: `build_graph` (existing), `ingest_agents`, `make_search`, `SharedVectorStore`, `HashEmbedder`, `write_graph_files`.
- Produces: proof that the graph's researcher node answers from the shared store, and the documented usage.
- [ ] **Step 1: Write the failing test**

```python
# tests/test_rag_graph_e2e.py
"""The graph's researcher node reads from the shared multi-agent store."""

from __future__ import annotations

from pathlib import Path

from langchain_core.language_models.fake_chat_models import FakeListChatModel

from orchestration.agent_rag import ingest_agents, make_search
from orchestration.embedding import HashEmbedder
from orchestration.graph import build_graph
from orchestration.graphic import write_graph_files
from orchestration.vectorstore import SharedVectorStore


def test_researcher_uses_the_shared_store_and_graph_is_drawn(tmp_path: Path) -> None:
    (tmp_path / "agents" / "RAG").mkdir(parents=True)
    (tmp_path / "agents" / "RAG" / "AGENTS.md").write_text(
        "# Retrieval\n\nFAISS vector index with reranking.\n", encoding="utf-8"
    )
    (tmp_path / "agents" / "Coder").mkdir()
    (tmp_path / "agents" / "Coder" / "AGENTS.md").write_text(
        "# Coder\n\nWrite python and run pytest.\n", encoding="utf-8"
    )
    embedder = HashEmbedder(dim=256)
    store = SharedVectorStore(dim=embedder.dim)
    ingest_agents(tmp_path / "agents", store, embedder)
    store.save(tmp_path / "idx")
    reloaded = SharedVectorStore.load(tmp_path / "idx")

    graph = build_graph(
        FakeListChatModel(responses=["faiss vector index", "final answer"]),
        make_search(reloaded, embedder, agent="RAG", k=2),
    )
    result = graph.invoke({"goal": "how do we index vectors?"})

    assert "FAISS vector index" in result["research"]
    assert "Coder/" not in result["research"]
    assert result["answer"] == "final answer"
    assert [p.name for p in write_graph_files(graph, tmp_path / "docs")] == ["graph.mmd", "graph.md"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pixi run python -m pytest tests/test_rag_graph_e2e.py -q --tb=short`
Expected: PASS immediately would mean the test proves nothing about new code; if it passes, temporarily break `make_search` (return `""`) to see it fail, then revert. If it fails for a real reason, fix the module it names. Every earlier task is already green, so the failure to look for is a wiring defect.

- [ ] **Step 3: Documentation and ignore rule**

Append to `.gitignore`:

```gitignore
# on-disk shared vector index (rebuilt by ingest_agents)
.vectors/
```

Add to `README.md` a section "Shared agent vector store and graph graphic" with this exact usage block:

````markdown
```python
from pathlib import Path
from orchestration.agent_rag import ingest_agents, make_search
from orchestration.embedding import default_embedder
from orchestration.graph import build_graph
from orchestration.graphic import write_graph_files
from orchestration.vectorstore import SharedVectorStore

embedder = default_embedder()          # hash offline; fastembed if installed
store = SharedVectorStore(embedder.dim)
ingest_agents(Path("Agents"), store, embedder)   # each subfolder = one agent's RAG
store.save(Path("Core/Orchestration/.vectors"))

graph = build_graph(llm, make_search(store, embedder, agent="RAG", k=4))
write_graph_files(graph, Path("Core/Orchestration/docs"), name="orchestration")
```

All agents share one FAISS index; an agent's chunks occupy ids `slot << 40 | n`.
Pass `agent=None` to search every agent at once. `HashEmbedder` measures word
overlap, not meaning; install `fastembed` for dense vectors.
````

- [ ] **Step 4: Full gate**

Run, from `Core/Orchestration`:

```bash
pixi run ruff format --check orchestration tests && pixi run ruff check orchestration tests && pixi run python -m compileall -q orchestration && pixi run python -m pytest -q --tb=short
```

Expected: all pass (12 existing tests + about 40 new). Lint the README: `rumdl-check README.md`. Then run the Workspace gate once: `cd /Users/usuario/Desktop/Workspace && pixi run python -m pytest Core Agents -q --tb=short` and report any failure by name, including ones that were already failing.

- [ ] **Step 5: Checkpoint**

GitKraken `git_status`, confirm the branch is not `main`, list the changed paths for the user, and wait for a request before committing.

---

## Self-Review

- **Spec coverage:** "Graphic generation module" is Task 1. "Embedding" is Task 2. "Vectorstore" is Tasks 3-4. "All agents together, share same vector" is the single `SharedVectorStore` index (Task 3). "Different positions" is the per-agent id block and the `agents()` slot map (Tasks 3-4). "Each subfolder is an agent RAG" is `ingest_agents` plus `make_search(agent=...)` (Task 5). The graph integration is Task 6.
- **Placeholder scan:** none left. Two inline corrections are written as instructions (the `TypedDict` for `_rows` in Task 3, the simplified `_markdown_files` in Task 5); the engineer applies them while implementing.
- **Type consistency:** `Hit`, `SharedVectorStore.add/search/agents/count/has_text/save/load`, `Embedder.embed(texts, *, query=False)`, `ingest_agents`, `make_search`, `write_graph_files` and `render_mermaid` match their File Structure signatures in every task.
- **Review Focus coverage:** items 1-3 and 6 are pinned in Task 3 and Task 5 tests, item 4 in Task 5, item 5 in Task 4.

## Known risks (unverified)

- `lazy import numpy as np` used in an annotation may need a `TYPE_CHECKING` import on the installed 3.15 build (Task 2, Step 4 gives the fallback).
- The id scheme caps an agent at about 1.1 trillion vectors and 2^23 agents; both are far beyond this workspace.
- `HashEmbedder` is lexical. The "same top-3 as Colab" check from `ColabLangSwarmPlan.md` Phase 2 applies only to dense embeddings and is out of scope here.
- The index is a flat exact index; for more than about 1 million chunks switch to an IVF index (not needed now).
