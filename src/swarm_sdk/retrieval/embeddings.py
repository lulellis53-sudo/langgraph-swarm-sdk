"""Local embedding and vector helpers."""

from __future__ import annotations

import hashlib
import importlib
import logging
from collections.abc import Iterable
from typing import Protocol, cast

import numpy as np

from swarm_sdk.gpu import batch_cosine

logger = logging.getLogger(__name__)


class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str], *, query: bool = False) -> np.ndarray: ...


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
        if kept_vectors:
            kept_matrix = np.stack(kept_vectors)
            similarities = batch_cosine(current, kept_matrix)
            if float(similarities.max()) >= threshold:
                continue
        kept_text.append(text)
        kept_vectors.append(current)
    return kept_text


def _bge_style(model_name: str) -> bool:
    return "bge" in model_name.lower()


def _prepare_texts(texts: list[str], *, query: bool, bge_style: bool) -> list[str]:
    if not bge_style:
        return texts
    if query:
        return [f"query: {t}" for t in texts]
    return [f"passage: {t}" for t in texts]


def _batched(texts: list[str], batch_size: int) -> Iterable[list[str]]:
    for start in range(0, len(texts), batch_size):
        yield texts[start : start + batch_size]


class HashEmbedder:
    """Deterministic unit vectors for tests and for machines without FastEmbed."""

    def __init__(self, dim: int = 384, batch_size: int = 64, model_name: str = "") -> None:
        self.dim = dim
        self.batch_size = batch_size
        self._bge = _bge_style(model_name)

    def embed(self, texts: list[str], *, query: bool = False) -> np.ndarray:
        prepared = _prepare_texts(texts, query=query, bge_style=self._bge)
        rows: list[np.ndarray] = []
        for batch in _batched(prepared, self.batch_size):
            rows.extend(self._one(text) for text in batch)
        if not rows:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.stack(rows)

    def _one(self, text: str) -> np.ndarray:
        seed = text.strip().lower().encode()
        digest = hashlib.sha256(seed).digest()
        rng = np.random.default_rng(int.from_bytes(digest[:8], "little"))
        vector = rng.standard_normal(self.dim).astype(np.float32)
        return unit(vector)


class FastEmbedder:
    """FastEmbed ONNX embedder. Default MiniLM-L6-v2 ships INT8 weights."""

    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        dim: int = 384,
        batch_size: int = 64,
    ) -> None:
        self.model_name = model_name
        self.dim = dim
        self.batch_size = batch_size
        self._bge = _bge_style(model_name)
        self._model: TextEmbeddingProto | None = None

    def embed(self, texts: list[str], *, query: bool = False) -> np.ndarray:
        prepared = _prepare_texts(texts, query=query, bge_style=self._bge)
        model = self._load()
        rows: list[np.ndarray] = []
        for batch in _batched(prepared, self.batch_size):
            rows.extend(np.asarray(vector, dtype=np.float32) for vector in model.embed(batch))
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


class _LlamaEmbedProto(Protocol):
    def embed(self, input: list[str], normalize: bool = True) -> Iterable[list[float]]: ...


class LlamaCppEmbedder:
    """llama.cpp embedder using a local GGUF model (Vulkan/Metal/CPU via llama-cpp-python)."""

    def __init__(
        self,
        model_path: str,
        dim: int = 384,
        batch_size: int = 64,
        n_ctx: int = 8192,
        **kwargs: object,
    ) -> None:
        self.model_path = model_path
        self.dim = dim
        self.batch_size = batch_size
        self.n_ctx = n_ctx
        self.kwargs = kwargs
        self._model: _LlamaEmbedProto | None = None

    def embed(self, texts: list[str], *, query: bool = False) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        model = self._load()
        prepared = _prepare_texts(texts, query=query, bge_style=_bge_style(self.model_path))
        rows: list[np.ndarray] = []
        for batch in _batched(prepared, self.batch_size):
            raw = model.embed(batch, normalize=True)
            for vec in raw:
                rows.append(np.asarray(vec, dtype=np.float32))
        return np.stack(rows)

    def _load(self) -> _LlamaEmbedProto:
        if self._model is None:
            try:
                module = importlib.import_module("llama_cpp")
            except ImportError as exc:
                raise ImportError(
                    "llama-cpp-python is not installed. Install with "
                    "CMAKE_ARGS='-DGGML_VULKAN=on' uv pip install llama-cpp-python"
                ) from exc
            llama_cls = getattr(module, "Llama")
            kwargs: dict[str, object] = {
                "model_path": self.model_path,
                "embedding": True,
                "n_ctx": self.n_ctx,
                "verbose": False,
                **self.kwargs,
            }
            self._model = cast(_LlamaEmbedProto, llama_cls(**kwargs))
        return self._model


class TextEmbeddingProto(Protocol):
    def embed(
        self,
        documents: list[str],
        batch_size: int = 256,
        parallel: int | None = None,
        **kwargs: object,
    ) -> Iterable[Iterable[float]]: ...


__all__ = [
    "Embedder",
    "FastEmbedder",
    "HashEmbedder",
    "LlamaCppEmbedder",
    "cosine",
    "dedupe_texts",
    "unit",
]
