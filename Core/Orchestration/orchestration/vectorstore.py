"""One shared FAISS index; every agent owns a block of ids ("positions").

Id layout: ``id = (slot << 40) | local``. ``slot`` is the agent's order of first
appearance; ``local`` counts that agent's vectors from 0. Vectors are expected
to be L2-normalized, so inner product equals cosine similarity.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

lazy import faiss
lazy import numpy as np

if TYPE_CHECKING:
    import numpy.typing as npt

__all__ = ["Hit", "SharedVectorStore"]

_SLOT_SHIFT = 40
_LOCAL_MASK = (1 << _SLOT_SHIFT) - 1


class _Row(TypedDict):
    agent: str
    source: str
    chunk: int
    text: str


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
        self._rows: dict[int, _Row] = {}
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

    def add(self, agent: str, source: str, chunk: int, text: str, vector: npt.NDArray) -> int:
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

    def search(self, vector: npt.NDArray, k: int = 4, *, agent: str | None = None) -> list[Hit]:
        """Return up to ``k`` nearest chunks, optionally restricted to one agent.

        Raises:
            ValueError: If ``vector`` does not have ``dim`` floats.
        """
        row = self._check(vector)
        if k <= 0 or not self._rows:
            return []
        params = None
        pool = len(self._rows)
        if agent is not None:
            ids = [p for p, meta in self._rows.items() if meta["agent"] == agent]
            if not ids:
                return []
            pool = len(ids)
            params = faiss.SearchParameters()
            params.sel = faiss.IDSelectorBatch(np.array(ids, dtype=np.int64))
        scores, found = self._index.search(row, min(k, pool), params=params)
        hits: list[Hit] = []
        for score, position in zip(scores[0], found[0], strict=True):
            if position < 0:
                continue
            meta = self._rows[int(position)]
            hits.append(Hit(id=int(position), score=float(score), **meta))
        return hits

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
            raw = json.loads(line)
            position = int(raw["id"])
            row: _Row = {
                "agent": raw["agent"],
                "source": raw["source"],
                "chunk": int(raw["chunk"]),
                "text": raw["text"],
            }
            store._rows[position] = row
            store._next_local[row["agent"]] = max(
                store._next_local.get(row["agent"], 0), (position & _LOCAL_MASK) + 1
            )
            store._seen.add((row["agent"], _digest(row["text"])))
        return store

    def _check(self, vector: npt.NDArray) -> npt.NDArray:
        row = np.ascontiguousarray(np.asarray(vector, dtype=np.float32).reshape(1, -1))
        if row.shape[1] != self.dim:
            raise ValueError(f"vector dim {row.shape[1]} does not match store dim {self.dim}")
        return row
