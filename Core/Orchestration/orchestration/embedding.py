"""Text embedders for the shared agent vector store.

``HashEmbedder`` is offline and deterministic (feature-hashed bag of words): it
measures word overlap, not meaning. ``FastEmbedEmbedder`` gives real dense
vectors when ``fastembed`` is installed (no cp315 ``onnxruntime`` wheel exists
on this Intel Mac, so ``auto`` falls back to hashing here).
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import re
from typing import TYPE_CHECKING, Protocol

lazy import numpy as np

if TYPE_CHECKING:
    import numpy.typing as npt

__all__ = ["Embedder", "FastEmbedEmbedder", "HashEmbedder", "default_embedder"]

_WORD = re.compile(r"\w+")
DEFAULT_DIM = 384


class Embedder(Protocol):
    """Batch text embedder returning unit-norm float32 rows."""

    dim: int

    def embed(self, texts: list[str], *, query: bool = False) -> npt.NDArray:
        """Embed ``texts``; ``query`` selects the query-side representation."""
        ...


class HashEmbedder:
    """Deterministic feature-hashed bag-of-words embedder (blake2b, not ``hash()``)."""

    def __init__(self, dim: int = DEFAULT_DIM) -> None:
        """Create an embedder with ``dim`` hashed features.

        Raises:
            ValueError: If ``dim`` is not positive.
        """
        if dim < 1:
            raise ValueError(f"dim must be positive, got {dim}")
        self.dim = dim

    def embed(self, texts: list[str], *, query: bool = False) -> npt.NDArray:
        """Return one L2-normalized row per text; ``query`` is ignored."""
        del query
        rows = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in _WORD.findall(text.casefold()):
                digest = hashlib.blake2b(word.encode(), digest_size=8).digest()
                value = int.from_bytes(digest, "little")
                rows[row, value % self.dim] += 1.0 if (value >> 63) & 1 else -1.0
            norm = float(np.linalg.norm(rows[row]))
            if norm:
                rows[row] /= norm
        return rows


class FastEmbedEmbedder:
    """Dense embeddings through ``fastembed`` (imported when constructed)."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5", dim: int = DEFAULT_DIM) -> None:
        """Load the model. Requires ``fastembed``; raises ``ImportError`` if missing."""
        from fastembed import TextEmbedding

        self.dim = dim
        self._model = TextEmbedding(model_name=model_name)

    def embed(self, texts: list[str], *, query: bool = False) -> npt.NDArray:
        """Embed and L2-normalize; ``query`` is ignored (bge needs no prefix here)."""
        del query
        rows = np.asarray(list(self._model.embed(texts)), dtype=np.float32).reshape(len(texts), -1)
        norms = np.linalg.norm(rows, axis=1, keepdims=True)
        return rows / np.where(norms == 0, 1.0, norms)


def default_embedder() -> Embedder:
    """Pick an embedder from ``ORCHESTRATION_EMBED_BACKEND`` (auto | hash | fastembed).

    Raises:
        ValueError: If the variable holds any other value.
    """
    backend = os.environ.get("ORCHESTRATION_EMBED_BACKEND", "auto").strip().lower()
    if backend not in {"auto", "hash", "fastembed"}:
        raise ValueError("ORCHESTRATION_EMBED_BACKEND must be auto, hash, or fastembed")
    if backend == "hash" or (backend == "auto" and importlib.util.find_spec("fastembed") is None):
        return HashEmbedder()
    return FastEmbedEmbedder()
