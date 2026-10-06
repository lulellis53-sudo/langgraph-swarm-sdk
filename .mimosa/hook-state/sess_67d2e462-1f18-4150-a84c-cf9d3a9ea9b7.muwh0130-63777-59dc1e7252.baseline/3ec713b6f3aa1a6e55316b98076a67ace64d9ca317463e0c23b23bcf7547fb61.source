"""Qdrant memory. Imported only when the qdrant extra is installed."""

from __future__ import annotations

import numpy as np

from swarm_sdk.memory.base import MemoryHit
from swarm_sdk.retrieval.embeddings import unit


def _quantization(mode: str) -> object | None:
    """Scalar int8. Qdrant GPU indexing is a CUDA server build, not this local client."""
    if mode != "int8":
        return None
    from qdrant_client.models import ScalarQuantization, ScalarQuantizationConfig, ScalarType

    return ScalarQuantization(scalar=ScalarQuantizationConfig(type=ScalarType.INT8))


class QdrantStore:
    """Qdrant-backed memory store (remote host over gRPC/HTTP)."""

    def __init__(self, path: str, dim: int, *, quantization: str = "none") -> None:
        """Connect to the Qdrant host and open ``collection``."""
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams

        self.dim = dim
        self.quantization = quantization
        self._collection = "memories"
        location = ":memory:" if path in {":memory:", ""} else path
        self._client = QdrantClient(path=location)
        if not self._client.collection_exists(self._collection):
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
                quantization_config=_quantization(quantization),
            )
        self._next_id = 1

    def add(self, text: str, vector: np.ndarray) -> int:
        """Upsert one record into the collection."""
        from qdrant_client.models import PointStruct

        row_id = self._next_id
        self._next_id += 1
        self._client.upsert(
            collection_name=self._collection,
            points=[
                PointStruct(
                    id=row_id,
                    vector=unit(vector).tolist(),
                    payload={"text": text},
                )
            ],
        )
        return row_id

    def search(self, vector: np.ndarray, k: int) -> list[MemoryHit]:
        """Query the collection with the given vector."""
        if k < 1:
            return []
        response = self._client.query_points(
            collection_name=self._collection,
            query=unit(vector).tolist(),
            limit=k,
        )
        hits: list[MemoryHit] = []
        for point in response.points:
            payload = point.payload or {}
            hits.append(
                MemoryHit(
                    id=int(point.id),
                    text=str(payload.get("text", "")),
                    score=float(point.score),
                )
            )
        return hits
