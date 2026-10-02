from typing import Protocol

import numpy as np
from pydantic import BaseModel


class MemoryHit(BaseModel):
    id: int
    text: str
    score: float


class MemoryStore(Protocol):
    def add(self, text: str, vector: np.ndarray) -> int: ...

    def search(self, vector: np.ndarray, k: int) -> list[MemoryHit]: ...


class BriefCache(Protocol):
    """Key/value cache surface (query-brief caching); separate from vector search."""

    def get(self, key: str, *, max_age_s: float | None = None) -> str | None: ...

    def put(self, key: str, value: str) -> None: ...
