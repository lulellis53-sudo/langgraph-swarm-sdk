"""Tests for the llama.cpp embedder using a mocked Llama class."""

from __future__ import annotations

import types
from unittest.mock import patch

import numpy as np
import pytest

from swarm_sdk.embeddings import LlamaCppEmbedder


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
