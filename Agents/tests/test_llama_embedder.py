"""Tests for the llama.cpp embedder using a mocked Llama class."""

from __future__ import annotations

import types
from unittest.mock import patch

import numpy as np
import pytest

from swarm_sdk.retrieval.embeddings import LlamaCppEmbedder


class _FakeLlama:
    def __init__(self, model_path: str, **kwargs: object) -> None:
        self.model_path = model_path
        self.kwargs = kwargs

    def embed(self, input: list[str], normalize: bool = True) -> list[list[float]]:
        del normalize
        rng = np.random.default_rng(sum(ord(c) for c in "".join(input)))
        return [rng.standard_normal(384).tolist() for _ in input]


def _fake_llama_module() -> types.ModuleType:
    module = types.ModuleType("llama_cpp")
    setattr(module, "Llama", _FakeLlama)
    return module


def test_llama_embedder_shape_and_dtype():
    fake = _fake_llama_module()
    with patch.dict("sys.modules", {"llama_cpp": fake}):
        embedder = LlamaCppEmbedder("/tmp/model.gguf", dim=384, batch_size=2)
        texts = ["one", "two", "three"]
        vectors = embedder.embed(texts)
        assert vectors.shape == (3, 384)
        assert vectors.dtype == np.float32


def test_llama_embedder_empty_input():
    fake = _fake_llama_module()
    with patch.dict("sys.modules", {"llama_cpp": fake}):
        embedder = LlamaCppEmbedder("/tmp/model.gguf", dim=384)
        vectors = embedder.embed([])
        assert vectors.shape == (0, 384)


def test_llama_embedder_missing_dependency():
    with patch.dict("sys.modules", {"llama_cpp": None}):
        embedder = LlamaCppEmbedder("/tmp/model.gguf", dim=384)
        with pytest.raises(ImportError):
            embedder.embed(["hello"])


def test_bge_uses_query_and_passage_prefixes_and_gpu_settings():
    seen: list[str] = []

    class BgeLlama(_FakeLlama):
        def __init__(self, model_path: str, **kwargs: object) -> None:
            super().__init__(model_path, **kwargs)
            assert kwargs["n_gpu_layers"] == 99
            assert kwargs["n_ctx"] == 2048
            assert kwargs["n_batch"] == 8

        def embed(self, input: list[str], normalize: bool = True) -> list[list[float]]:
            del normalize
            seen.extend(input)
            return [np.ones(1024, dtype=np.float32).tolist() for _ in input]

    fake = types.ModuleType("llama_cpp")
    setattr(fake, "Llama", BgeLlama)
    with patch.dict("sys.modules", {"llama_cpp": fake}):
        embedder = LlamaCppEmbedder(
            "/models/bge-m3-q8_0.gguf",
            dim=1024,
            n_ctx=2048,
            n_gpu_layers=99,
            n_batch=8,
        )
        assert embedder.embed(["find similar"], query=True).shape == (1, 1024)
        assert embedder.embed(["memory passage"], query=False).shape == (1, 1024)

    assert seen == ["query: find similar", "passage: memory passage"]
