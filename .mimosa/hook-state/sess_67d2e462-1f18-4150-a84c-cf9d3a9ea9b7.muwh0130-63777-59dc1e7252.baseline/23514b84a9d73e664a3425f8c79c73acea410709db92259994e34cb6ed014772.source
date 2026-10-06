"""Deterministic bag-of-words embedder for offline retrieval tests."""

from __future__ import annotations

import hashlib
import re

import numpy as np

_WORD = re.compile(r"\w+")


class BagOfWordsEmbedder:
    """Hash each lowercase word into one of ``dim`` buckets and L2-normalize the counts."""

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def embed(self, texts: list[str], *, query: bool = False) -> np.ndarray:
        del query
        rows = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in _WORD.findall(text.lower()):
                digest = hashlib.blake2b(word.encode(), digest_size=4).digest()
                rows[row, int.from_bytes(digest, "little") % self.dim] += 1.0
        norms = np.linalg.norm(rows, axis=1, keepdims=True)
        norms[norms == 0.0] = 1.0
        return rows / norms


__all__ = ["BagOfWordsEmbedder"]
