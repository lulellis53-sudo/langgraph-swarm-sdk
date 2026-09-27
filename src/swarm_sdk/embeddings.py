"""Local embedding and vector helpers."""

from __future__ import annotations

import hashlib
import importlib
from collections.abc import Iterable
from typing import Protocol, cast

import numpy as np


class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> np.ndarray: ...


def unit(vector: np.ndarray) -> np.ndarray:
    array = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(array))
    if norm == 0.0:
        return array
    return array / norm


def cosine(left: np.ndarray, right: np.ndarray) -> float:
    return float(np.dot(unit(left), unit(right)))


def dedupe_texts(texts: list[str], vectors: np.ndarray, threshold: float) -> list[str]:
    """Drop near-duplicate passages before they enter the prompt."""
    kept_text: list[str] = []
    kept_vectors: list[np.ndarray] = []
    for text, vector in zip(texts, vectors, strict=True):
        current = unit(vector)
        if any(float(np.dot(current, other)) >= threshold for other in kept_vectors):
            continue
        kept_text.append(text)
        kept_vectors.append(current)
    return kept_text


class HashEmbedder:
    """Deterministic unit vectors for tests and for machines without FastEmbed."""

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> np.ndarray:
        rows = [self._one(text) for text in texts]
        if not rows:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.stack(rows)

    def _one(self, text: str) -> np.ndarray:
        seed = text.strip().lower().split(":", 1)[0].encode()
        digest = hashlib.sha256(seed).digest()
        rng = np.random.default_rng(int.from_bytes(digest[:8], "little"))
        vector = rng.standard_normal(self.dim).astype(np.float32)
        return unit(vector)


class FastEmbedder:
    """FastEmbed ONNX embedder. Default model ships int8 weights."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5", dim: int = 384) -> None:
        self.model_name = model_name
        self.dim = dim
        self._model: TextEmbeddingProto | None = None

    def embed(self, texts: list[str]) -> np.ndarray:
        model = self._load()
        rows = [np.asarray(vector, dtype=np.float32) for vector in model.embed(texts)]
        if not rows:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.vstack(rows)

    def _load(self) -> TextEmbeddingProto:
        if self._model is None:
            try:
                module = importlib.import_module("fastembed")
            except ImportError as exc:
                raise ImportError(
                    "fastembed is not installed. onnxruntime publishes no macOS x86_64 wheel, "
                    "so FastEmbed cannot be installed on Intel Macs."
                ) from exc
            embedding_cls = getattr(module, "TextEmbedding")
            self._model = cast(TextEmbeddingProto, embedding_cls(model_name=self.model_name))
        return self._model


class TextEmbeddingProto(Protocol):
    def embed(self, texts: list[str]) -> Iterable[object]: ...
