"""Structural entry-point protocols shared across retrieval, search and memory.

These mirror the dominant signatures found in the codebase; concrete classes
conform structurally (PEP 544) without inheriting anything.
"""

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import numpy as np

    from swarm_sdk.memory.base import MemoryHit


class SearchFn(Protocol):
    """Vector similarity search: one query vector, ``k`` nearest hits."""

    def search(self, vector: np.ndarray, k: int) -> list[MemoryHit]:
        """Return the ``k`` stored records most similar to ``vector``."""


class EmbedFn(Protocol):
    """Batch-embed texts into unit-normalized float32 rows."""

    def embed(self, texts: list[str], *, query: bool = False) -> np.ndarray:
        """Embed ``texts`` into one row per text; ``query`` selects query-side prefixing."""


class RerankFn(Protocol):
    """Rerank documents best-first for a query."""

    def rerank(self, query: str, documents: list[str]) -> list[str]:
        """Return ``documents`` ordered best-first for ``query``."""


__all__ = ["EmbedFn", "RerankFn", "SearchFn"]
