"""In-memory vector store with OpenCL brute-force inner-product search."""

from __future__ import annotations

import threading

import numpy as np

from swarm_sdk.embeddings import unit
from swarm_sdk.gpu import topk_ip
from swarm_sdk.memory.base import MemoryHit


class OpenClVecStore:
    """Brute-force vector store that runs search on the GPU when possible.

    Vectors are kept in a contiguous float32 buffer. Search uses the shared
    OpenCL dispatcher (`swarm_sdk.gpu.topk_ip`) and falls back to NumPy if
    OpenCL is unavailable or fails.
    """

    def __init__(self, dim: int) -> None:
        self.dim = dim
        self._texts: list[str] = []
        self._vectors: np.ndarray = np.zeros((0, dim), dtype=np.float32)
        self._lock = threading.Lock()

    def add(self, text: str, vector: np.ndarray) -> int:
        row = unit(vector).reshape(1, -1).astype(np.float32)
        if row.shape[1] != self.dim:
            raise ValueError(f"expected dim {self.dim}, got {row.shape[1]}")
        with self._lock:
            index = len(self._texts)
            self._texts.append(text)
            self._vectors = np.vstack([self._vectors, row])
            return index

    def search(self, vector: np.ndarray, k: int) -> list[MemoryHit]:
        if k < 1:
            return []
        query = unit(vector).reshape(-1).astype(np.float32)
        if query.shape[0] != self.dim:
            raise ValueError(f"expected dim {self.dim}, got {query.shape[0]}")

        with self._lock:
            matrix = self._vectors
            texts = list(self._texts)

        if matrix.shape[0] == 0:
            return []

        idx, scores = topk_ip(query, matrix, min(k, matrix.shape[0]))
        hits: list[MemoryHit] = []
        for i, score in zip(idx, scores, strict=True):
            hits.append(MemoryHit(id=int(i), text=texts[int(i)], score=float(score)))
        return hits
