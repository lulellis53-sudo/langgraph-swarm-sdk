"""In-memory vector store with OpenCL brute-force inner-product search."""

from __future__ import annotations

import threading

import numpy as np

from swarm_sdk.gpu import topk_ip
from swarm_sdk.memory.base import MemoryHit
from swarm_sdk.retrieval.embeddings import unit


class OpenClVecStore:
    """Brute-force vector store that runs search on the GPU when possible.

    Vectors are kept in a contiguous float32 buffer. Search uses the shared
    OpenCL dispatcher (`swarm_sdk.gpu.topk_ip`) and falls back to NumPy if
    OpenCL is unavailable or fails.
    """

    def __init__(
        self,
        dim: int,
        *,
        max_vectors: int = 4096,
        chunk_rows: int = 256,
    ) -> None:
        if dim < 1 or max_vectors < 1 or chunk_rows < 1:
            raise ValueError("dim, max_vectors, and chunk_rows must be >= 1")
        self.dim = dim
        self.max_vectors = max_vectors
        self.chunk_rows = chunk_rows
        self._texts: list[str | None] = []
        self._ids = np.empty(0, dtype=np.int64)
        self._vectors = np.empty((0, dim), dtype=np.float32)
        self._capacity = 0
        self._size = 0
        self._head = 0
        self._next_id = 0
        self._generation = 0
        self._cache_token = object()
        self._lock = threading.Lock()

    @property
    def resident_bytes(self) -> int:
        """Bytes occupied by resident float32 vectors (excludes Python text objects)."""
        with self._lock:
            return int(self._vectors.nbytes)

    def add(self, text: str, vector: np.ndarray) -> int:
        row = unit(vector).reshape(1, -1).astype(np.float32)
        if row.shape[1] != self.dim:
            raise ValueError(f"expected dim {self.dim}, got {row.shape[1]}")
        with self._lock:
            index = self._next_id
            self._next_id += 1
            if self._size < self.max_vectors:
                if self._size == self._capacity:
                    capacity = min(self.max_vectors, max(1, self._capacity * 2))
                    vectors = np.empty((capacity, self.dim), dtype=np.float32)
                    ids = np.empty(capacity, dtype=np.int64)
                    vectors[: self._size] = self._vectors[: self._size]
                    ids[: self._size] = self._ids[: self._size]
                    self._vectors = vectors
                    self._ids = ids
                    self._texts.extend([None] * (capacity - self._capacity))
                    self._capacity = capacity
                slot = (self._head + self._size) % self.max_vectors
                self._size += 1
            else:
                slot = self._head
                self._head = (self._head + 1) % self.max_vectors
            self._vectors[slot] = row[0]
            self._texts[slot] = text
            self._ids[slot] = index
            self._generation += 1
            return index

    def search(self, vector: np.ndarray, k: int) -> list[MemoryHit]:
        if k < 1:
            return []
        query = unit(vector).reshape(-1).astype(np.float32)
        if query.shape[0] != self.dim:
            raise ValueError(f"expected dim {self.dim}, got {query.shape[0]}")

        with self._lock:
            if self._size == 0:
                return []

            best_scores = np.empty(0, dtype=np.float32)
            best_indexes = np.empty(0, dtype=np.int64)
            for start in range(0, self._size, self.chunk_rows):
                stop = min(start + self.chunk_rows, self._size)
                logical = np.arange(start, stop, dtype=np.int64)
                slots = (self._head + logical) % self.max_vectors
                if slots[-1] - slots[0] == len(slots) - 1:
                    chunk = self._vectors[slots[0] : slots[-1] + 1]
                else:
                    chunk = self._vectors[slots]
                local_idx, local_scores = topk_ip(
                    query,
                    chunk,
                    k,
                    cache_key=(self._cache_token, self._generation, start, stop),
                )
                local_idx = slots[local_idx]
                candidates_idx = np.concatenate((best_indexes, local_idx))
                candidates_scores = np.concatenate((best_scores, local_scores))
                count = min(k, candidates_scores.size)
                selected = np.argpartition(candidates_scores, -count)[-count:]
                selected = selected[np.argsort(-candidates_scores[selected])]
                best_indexes = candidates_idx[selected]
                best_scores = candidates_scores[selected]

            return [
                MemoryHit(
                    id=int(self._ids[int(index)]),
                    text=str(self._texts[int(index)]),
                    score=float(score),
                )
                for index, score in zip(best_indexes, best_scores, strict=True)
            ]
