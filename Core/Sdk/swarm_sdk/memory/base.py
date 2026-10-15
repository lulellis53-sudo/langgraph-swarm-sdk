"""Memory store protocol and the hit record it returns."""

from __future__ import annotations

from typing import Protocol

import numpy as np
from pydantic import BaseModel


class MemoryHit(BaseModel):
    """One search result: record id, stored text, and similarity score."""

    id: int
    text: str
    score: float


class MemoryStore(Protocol):
    """Vector store that persists texts and returns nearest neighbours."""

    def add(self, text: str, vector: np.ndarray) -> int:
        """Store ``text`` (with its embedding) and return the new record id."""

    def search(self, vector: np.ndarray, k: int) -> list[MemoryHit]:
        """Return the ``k`` stored records most similar to the query."""


class BriefCache(Protocol):
    """Key/value cache surface (query-brief caching); separate from vector search."""

    def get(self, key: str, *, max_age_s: float | None = None) -> str | None:
        """Return the cached value for ``key``, or ``None`` when absent or expired."""

    def put(self, key: str, value: str) -> None:
        """Cache ``value`` under ``key``."""
