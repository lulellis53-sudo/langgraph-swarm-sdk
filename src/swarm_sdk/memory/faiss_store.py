"""FAISS inner-product index. Imported only when the faiss extra is installed."""

from __future__ import annotations

import numpy as np

from swarm_sdk.embeddings import unit
from swarm_sdk.memory.base import MemoryHit


def _try_cuda_index(faiss: object, index: object) -> tuple[object, str, object | None]:
    """Move a CPU index to CUDA device 0. Radeon / OpenCL / MoltenVK are not supported."""
    resources_cls = getattr(faiss, "StandardGpuResources", None)
    to_gpu = getattr(faiss, "index_cpu_to_gpu", None)
    if resources_cls is None or to_gpu is None:
        return index, "cpu", None
    try:
        resources = resources_cls()
        gpu_index = to_gpu(resources, 0, index)
    except Exception:
        return index, "cpu", None
    return gpu_index, "cuda", resources


class FaissStore:
    def __init__(self, dim: int, *, gpu: bool = False) -> None:
        import faiss

        self.dim = dim
        self._faiss = faiss
        self._gpu_resources: object | None = None
        index = faiss.IndexFlatIP(dim)
        self.device = "cpu"
        if gpu:
            index, self.device, self._gpu_resources = _try_cuda_index(faiss, index)
        self._index = index
        self._texts: list[str] = []

    def add(self, text: str, vector: np.ndarray) -> int:
        row = unit(vector).reshape(1, -1).astype(np.float32)
        self._index.add(row)
        self._texts.append(text)
        return len(self._texts) - 1

    def search(self, vector: np.ndarray, k: int) -> list[MemoryHit]:
        total = int(self._index.ntotal)
        if total == 0 or k < 1:
            return []
        query = unit(vector).reshape(1, -1).astype(np.float32)
        scores, ids = self._index.search(query, min(k, total))
        hits: list[MemoryHit] = []
        for score, idx in zip(scores[0], ids[0], strict=True):
            index = int(idx)
            if index < 0:
                continue
            hits.append(MemoryHit(id=index, text=self._texts[index], score=float(score)))
        return hits
