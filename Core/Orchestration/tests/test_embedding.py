"""Embedders: deterministic, normalized, offline by default."""

from __future__ import annotations

import numpy as np
import pytest

from orchestration.embedding import HashEmbedder, default_embedder


def test_hash_embedder_shape_dtype_and_unit_norm() -> None:
    vectors = HashEmbedder(dim=64).embed(["alpha beta", "gamma"])
    assert vectors.shape == (2, 64)
    assert vectors.dtype == np.float32
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5)


def test_hash_embedder_is_deterministic_across_calls() -> None:
    embedder = HashEmbedder(dim=64)
    assert np.array_equal(embedder.embed(["same text"]), embedder.embed(["same text"]))


def test_shared_words_score_higher_than_unrelated_words() -> None:
    embedder = HashEmbedder(dim=256)
    a, b, c = embedder.embed(["faiss vector index", "vector index search", "banana bread recipe"])
    assert float(a @ b) > float(a @ c)


def test_empty_text_gives_zero_row_not_nan() -> None:
    row = HashEmbedder(dim=16).embed([""])[0]
    assert not np.isnan(row).any()
    assert float(np.linalg.norm(row)) == 0.0


def test_hash_embedder_rejects_non_positive_dim() -> None:
    with pytest.raises(ValueError, match="dim"):
        HashEmbedder(dim=0)


def test_default_embedder_honours_hash_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCHESTRATION_EMBED_BACKEND", "hash")
    assert isinstance(default_embedder(), HashEmbedder)


def test_default_embedder_rejects_unknown_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCHESTRATION_EMBED_BACKEND", "nope")
    with pytest.raises(ValueError, match="ORCHESTRATION_EMBED_BACKEND"):
        default_embedder()
