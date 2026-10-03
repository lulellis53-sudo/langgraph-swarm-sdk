"""Local embedding and vector helpers."""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import urllib.error
import urllib.request
from collections.abc import Iterable
from email.message import Message
from typing import IO, Protocol, cast
from urllib.parse import urlsplit

import numpy as np

from swarm_sdk.gpu import batch_cosine

logger = logging.getLogger(__name__)


class Embedder(Protocol):
    """Embedding backend protocol: batch texts to unit-normalized float32 rows."""

    dim: int

    def embed(self, texts: list[str], *, query: bool = False) -> np.ndarray: ...


def unit(vector: np.ndarray) -> np.ndarray:
    r"""L2-normalize a vector.

    .. math::
        \hat{x} = \frac{x}{\|x\|_2}

    Zero vectors are returned unchanged to avoid division by zero.
    """
    array = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(array))
    if norm == 0.0:
        return array
    return array / norm


def cosine(left: np.ndarray, right: np.ndarray) -> float:
    r"""Cosine similarity between two vectors.

    .. math::
        \operatorname{cos}(u, v) =
            \frac{u \cdot v}{\|u\|_2 \cdot \|v\|_2}

    Returns a value in :math:`[-1, 1]`. Zero vectors yield ``0.0``.
    """
    return float(np.dot(unit(left), unit(right)))


def dedupe_texts(texts: list[str], vectors: np.ndarray, threshold: float) -> list[str]:
    r"""Drop near-duplicate passages before they enter the prompt.

    A passage is skipped when its cosine similarity to any already-kept
    passage is at least ``threshold``:

    .. math::
        \operatorname{sim}(u, v) = \frac{u \cdot v}{\|u\|_2 \cdot \|v\|_2}
        \ge \theta
    """
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
    """True when the model expects ``query:``/``passage:`` prefixes.

    BGE v1.x wants the prefixes; BGE-M3 is trained without them, so its name
    is excluded even though it contains "bge".
    """
    lowered = model_name.lower()
    return "bge" in lowered and "m3" not in lowered


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


class EmbeddingServerError(RuntimeError):
    """Raised when the llama-server embedding endpoint fails or answers badly."""


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class _RefuseRedirect(urllib.request.HTTPRedirectHandler):
    """Fail on any redirect so text never leaves the validated loopback host."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: Message,
        newurl: str,
    ) -> None:
        """Raise instead of following ``newurl``."""
        raise urllib.error.HTTPError(req.full_url, code, "redirect refused", headers, fp)


_NO_REDIRECT_OPENER = urllib.request.build_opener(_RefuseRedirect)


class LlamaServerEmbedder:
    """Embedder for a local ``llama-server --embedding`` (Vulkan0 on the Radeon 5300M).

    Talks to the OpenAI-compatible ``/v1/embeddings`` route. Only loopback URLs are
    accepted so repository text never leaves the machine.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080",
        *,
        model: str = "bge-m3",
        dim: int = 1024,
        batch_size: int = 8,
        timeout_s: float = 30.0,
    ) -> None:
        parts = urlsplit(base_url)
        if parts.scheme != "http" or parts.hostname not in _LOOPBACK_HOSTS:
            raise ValueError(f"llama-server URL must be an http loopback address: {base_url!r}")
        self.url = f"{base_url.rstrip('/')}/v1/embeddings"
        self.model = model
        self.dim = dim
        self.batch_size = batch_size
        self.timeout_s = timeout_s

    def embed(self, texts: list[str], *, query: bool = False) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        prepared = _prepare_texts(texts, query=query, bge_style=_bge_style(self.model))
        rows = [vec for batch in _batched(prepared, self.batch_size) for vec in self._post(batch)]
        return np.stack(rows)

    def _post(self, batch: list[str]) -> list[np.ndarray]:
        request = urllib.request.Request(
            self.url,
            data=json.dumps({"input": batch, "model": self.model}).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with _NO_REDIRECT_OPENER.open(request, timeout=self.timeout_s) as response:
                payload = json.loads(response.read())
            items = sorted(payload["data"], key=lambda item: item["index"])
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise EmbeddingServerError(f"llama-server request failed: {exc}") from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise EmbeddingServerError(f"unexpected llama-server response: {exc}") from exc
        if len(items) != len(batch):
            raise EmbeddingServerError(f"expected {len(batch)} embeddings, got {len(items)}")
        vectors = [unit(np.asarray(item["embedding"], dtype=np.float32)) for item in items]
        for vec in vectors:
            if vec.shape[0] != self.dim:
                raise EmbeddingServerError(
                    f"embedding dimension {vec.shape[0]} != configured dim {self.dim}"
                )
        return vectors


class TextEmbeddingProto(Protocol):
    """Structural view of FastEmbed's TextEmbedding for type checking."""

    def embed(
        self,
        documents: list[str],
        batch_size: int = 256,
        parallel: int | None = None,
        **kwargs: object,
    ) -> Iterable[Iterable[float]]: ...


__all__ = [
    "Embedder",
    "EmbeddingServerError",
    "FastEmbedder",
    "HashEmbedder",
    "LlamaCppEmbedder",
    "LlamaServerEmbedder",
    "cosine",
    "dedupe_texts",
    "unit",
]
