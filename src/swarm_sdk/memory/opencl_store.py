"""In-memory vector store with OpenCL brute-force search (float32, INT8 or 1-bit)."""

from __future__ import annotations

import threading
from typing import Literal

import numpy as np

from swarm_sdk.gpu import binary_dot, binary_quantize, dequant_dot, quantize_int8, topk_ip
from swarm_sdk.memory.base import MemoryHit
from swarm_sdk.retrieval.embeddings import unit

Quantize = Literal["none", "int8", "binary"]


def _topk(scores: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    k = min(k, scores.shape[0])
    idx = np.argpartition(scores, -k)[-k:]
    idx = idx[np.argsort(-scores[idx])]
    return idx.astype(np.int64), scores[idx]


class OpenClVecStore:
    """Brute-force vector store that runs search on the GPU when possible.

    Vectors are kept in contiguous buffers whose element type depends on
    ``quantize``: float32 (``"none"``), symmetric per-row INT8 with a float32
    scale (``"int8"``), or packed sign bits (``"binary"``). Search uses the shared
    OpenCL dispatcher in `swarm_sdk.gpu` and falls back to NumPy if OpenCL is
    unavailable or fails. Scores are cosine similarities for ``"none"`` and
    ``"int8"``, and a cosine estimate derived from the Hamming distance for
    ``"binary"``, so a single threshold works across modes.
    """

    def __init__(
        self,
        dim: int,
        *,
        max_vectors: int = 4096,
        chunk_rows: int = 256,
        quantize: Quantize = "none",
    ) -> None:
        if dim < 1 or max_vectors < 1 or chunk_rows < 1:
            raise ValueError("dim, max_vectors, and chunk_rows must be >= 1")
        if quantize not in ("none", "int8", "binary"):
            raise ValueError(f"quantize must be none, int8 or binary, got {quantize!r}")
        self.dim = dim
        self.max_vectors = max_vectors
        self.chunk_rows = chunk_rows
        self._mode: Quantize = quantize
        self._layout = self._layout_for(quantize, dim)
        self._texts: list[str | None] = []
        self._ids = np.empty(0, dtype=np.int64)
        # All buffers exist so attribute access is statically known; only the layout's
        # buffers are ever grown or counted, the rest stay empty.
        self._vectors = np.empty((0, dim), dtype=np.float32)
        self._codes = np.empty((0, dim), dtype=np.int8)
        self._scales = np.empty(0, dtype=np.float32)
        self._bits = np.empty((0, (dim + 31) // 32), dtype=np.uint32)
        self._capacity = 0
        self._size = 0
        self._head = 0
        self._next_id = 0
        self._generation = 0
        self._cache_token = object()
        self._lock = threading.Lock()

    @staticmethod
    def _layout_for(mode: Quantize, dim: int) -> dict[str, tuple[tuple[int, ...], type]]:
        if mode == "int8":
            return {"_codes": ((dim,), np.int8), "_scales": ((), np.float32)}
        if mode == "binary":
            return {"_bits": (((dim + 31) // 32,), np.uint32)}
        return {"_vectors": ((dim,), np.float32)}

    @property
    def resident_bytes(self) -> int:
        """Bytes occupied by resident vector buffers (excludes Python text objects)."""
        with self._lock:
            return int(sum(getattr(self, name).nbytes for name in self._layout))

    def _grow(self, capacity: int) -> None:
        for name, (tail, dtype) in self._layout.items():
            grown = np.empty((capacity, *tail), dtype=dtype)
            grown[: self._size] = getattr(self, name)[: self._size]
            setattr(self, name, grown)
        ids = np.empty(capacity, dtype=np.int64)
        ids[: self._size] = self._ids[: self._size]
        self._ids = ids
        self._texts.extend([None] * (capacity - self._capacity))
        self._capacity = capacity

    def _write_slot(self, slot: int, row: np.ndarray) -> None:
        if self._mode == "int8":
            codes, scales = quantize_int8(row)
            self._codes[slot] = codes[0]
            self._scales[slot] = scales[0]
        elif self._mode == "binary":
            self._bits[slot] = binary_quantize(row)[0]
        else:
            self._vectors[slot] = row[0]

    def add(self, text: str, vector: np.ndarray) -> int:
        row = unit(vector).reshape(1, -1).astype(np.float32)
        if row.shape[1] != self.dim:
            raise ValueError(f"expected dim {self.dim}, got {row.shape[1]}")
        with self._lock:
            index = self._next_id
            self._next_id += 1
            if self._size < self.max_vectors:
                if self._size == self._capacity:
                    self._grow(min(self.max_vectors, max(1, self._capacity * 2)))
                slot = (self._head + self._size) % self.max_vectors
                self._size += 1
            else:
                slot = self._head
                self._head = (self._head + 1) % self.max_vectors
            self._write_slot(slot, row)
            self._texts[slot] = text
            self._ids[slot] = index
            self._generation += 1
            return index

    def _chunk(self, name: str, slots: np.ndarray) -> np.ndarray:
        array = getattr(self, name)
        if slots[-1] - slots[0] == len(slots) - 1:
            return array[slots[0] : slots[-1] + 1]
        return array[slots]

    def _score_chunk(
        self,
        query: np.ndarray,
        query_bits: np.ndarray,
        slots: np.ndarray,
        k: int,
        cache_key: object,
    ) -> tuple[np.ndarray, np.ndarray]:
        if self._mode == "int8":
            scores = dequant_dot(self._chunk("_codes", slots), self._chunk("_scales", slots), query)
            return _topk(scores, k)
        if self._mode == "binary":
            scores = binary_dot(self._chunk("_bits", slots), query_bits, dim=self.dim)
            idx, best = _topk(scores, k)
            return idx, np.cos(np.pi * (self.dim - best) / self.dim).astype(np.float32)
        return topk_ip(query, self._chunk("_vectors", slots), k, cache_key=cache_key)

    def search(self, vector: np.ndarray, k: int) -> list[MemoryHit]:
        if k < 1:
            return []
        query = unit(vector).reshape(-1).astype(np.float32)
        if query.shape[0] != self.dim:
            raise ValueError(f"expected dim {self.dim}, got {query.shape[0]}")
        query_bits = (
            binary_quantize(query)[0] if self._mode == "binary" else np.empty(0, dtype=np.uint32)
        )

        with self._lock:
            if self._size == 0:
                return []

            best_scores = np.empty(0, dtype=np.float32)
            best_indexes = np.empty(0, dtype=np.int64)
            for start in range(0, self._size, self.chunk_rows):
                stop = min(start + self.chunk_rows, self._size)
                logical = np.arange(start, stop, dtype=np.int64)
                slots = (self._head + logical) % self.max_vectors
                local_idx, local_scores = self._score_chunk(
                    query,
                    query_bits,
                    slots,
                    k,
                    (self._cache_token, self._generation, start, stop),
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
