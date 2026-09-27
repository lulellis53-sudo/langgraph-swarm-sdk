"""Qdrant memory. Imported only when the qdrant extra is installed."""

from __future__ import annotations

import numpy as np

from swarm_sdk.embeddings import unit
from swarm_sdk.memory.base import MemoryHit


class QdrantStore:
    def __init__(self, path: str, dim: int) -> None:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams

        self.dim = dim
        self._collection = "memories"
        location = ":memory:" if path in {":memory:", ""} else path
        self._client = QdrantClient(path=location)
        if not self._client.collection_exists(self._collection):
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )
        self._next_id = 1

    def add(self, text: str, vector: np.ndarray) -> int:
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
