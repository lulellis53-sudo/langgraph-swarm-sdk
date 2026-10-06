"""Extractive summary and semantic score of documents against a query."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import numpy as np

    from WebSearch.backend.docs import ExtractedDoc

_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"\w+")
_MIN_SENTENCE_CHARS = 20


class Embedder(Protocol):
    """Text embedder returning one unit vector per text."""

    def embed(self, texts: list[str], *, query: bool = False) -> np.ndarray: ...


class LexicalEmbedder:
    """Feature-hashed bag-of-words unit vectors: cosine = shared-vocabulary overlap.

    Deterministic (blake2b, not ``hash()``), no model download. It measures word overlap,
    not meaning; pass a model-backed :class:`Embedder` for true semantic similarity.
    """

    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim

    def embed(self, texts: list[str], *, query: bool = False) -> np.ndarray:
        """Return one L2-normalized row per text; ``query`` is ignored."""
        import numpy as np

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


def default_embedder() -> Embedder:
    """Choose dense local embeddings when installed; otherwise use lexical vectors.

    ``WEBSEARCH_EMBED_BACKEND=fastembed`` selects FastEmbed and accepts an
    optional model name in ``WEBSEARCH_EMBED_MODEL``. ``llama-cpp`` requires a
    local GGUF path in that variable. Auto mode uses FastEmbed when installed;
    unsupported systems use deterministic lexical vectors without a download.
    """
    backend = os.environ.get("WEBSEARCH_EMBED_BACKEND", "auto").strip().lower()
    model_name = os.environ.get("WEBSEARCH_EMBED_MODEL", "").strip()
    dim = int(os.environ.get("WEBSEARCH_EMBED_DIM", "384"))
    if dim < 1:
        raise ValueError("WEBSEARCH_EMBED_DIM must be positive")
    if backend == "lexical":
        return LexicalEmbedder(dim)
    if backend == "llama-cpp":
        if not model_name:
            raise ValueError("WEBSEARCH_EMBED_MODEL must be a local GGUF path for llama-cpp")
        from swarm_sdk.retrieval.embeddings import LlamaCppEmbedder

        return LlamaCppEmbedder(model_path=model_name, dim=dim)
    if backend not in {"auto", "fastembed"}:
        raise ValueError("WEBSEARCH_EMBED_BACKEND must be auto, fastembed, llama-cpp, or lexical")
    if backend == "auto" and importlib.util.find_spec("fastembed") is None:
        return LexicalEmbedder(dim)
    from swarm_sdk.retrieval.embeddings import FastEmbedder

    return FastEmbedder(
        model_name=model_name or "sentence-transformers/all-MiniLM-L6-v2", dim=dim
    )


@dataclass(frozen=True, slots=True)
class ScoredSummary:
    """Summary of one document and how close it is to the query.

    Attributes:
        url: Source document URL.
        summary: Best sentences in original order, capped at ``max_chars``.
        score: Mean cosine of the kept sentences to the query (-1..1, higher is closer).
    """

    url: str
    summary: str
    score: float


def summarize_score(
    docs: Sequence[ExtractedDoc],
    query: str,
    *,
    embedder: Embedder | None = None,
    max_sentences: int = 3,
    max_chars: int = 400,
) -> list[ScoredSummary]:
    """Summarize each doc with its sentences closest to ``query`` and score it.

    Args:
        docs: Normalized documents.
        query: What the summary should answer; embedded as a query.
        embedder: Default :func:`default_embedder`; lexical fallback is offline.
        max_sentences: Sentences kept per document.
        max_chars: Hard cap on summary length.

    Returns:
        One entry per document that has usable sentences, best score first.

    Raises:
        ValueError: On an empty query or non-positive limits.
    """
    if not query.strip():
        raise ValueError("query must not be empty")
    if max_sentences < 1 or max_chars < 1:
        raise ValueError("max_sentences and max_chars must be >= 1")
    if embedder is None:
        embedder = default_embedder()
    query_vec = embedder.embed([query], query=True)[0]

    results: list[ScoredSummary] = []
    for doc in docs:
        sentences = [s for s in _SENTENCE.split(doc.text) if len(s) >= _MIN_SENTENCE_CHARS]
        if not sentences:
            sentences = [doc.text] if doc.text else []
        if not sentences:
            continue
        sims = embedder.embed(sentences) @ query_vec
        top = sorted(sorted(range(len(sentences)), key=lambda i: -float(sims[i]))[:max_sentences])
        summary = " ".join(sentences[i] for i in top)[:max_chars].rstrip()
        results.append(ScoredSummary(doc.url, summary, float(sims[top].mean())))
    return sorted(results, key=lambda r: -r.score)


__all__ = [
    "Embedder",
    "LexicalEmbedder",
    "ScoredSummary",
    "default_embedder",
    "summarize_score",
]
