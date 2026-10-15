"""Qwen3-Embedding-0.6B (ONNX int8) embedder: formatting, pooling, threading, real model."""

from __future__ import annotations

import importlib.util
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from swarm_sdk.config.settings import Settings
from swarm_sdk.core.swarm import default_embedder
from swarm_sdk.retrieval.embeddings import QwenOnnxEmbedder

_DIM = 1024
_LAYERS = 28
_MODEL_DIR = Path(os.environ.get("SWARM_QWEN_ONNX_DIR", Path.home() / "build" / "qwen3-embed"))
_HAVE_MODEL = (_MODEL_DIR / "onnx" / "model_int8.onnx").is_file()
# onnxruntime is an optional extra with no cp315 wheels (see pyproject embed extra).
_HAVE_ONNX = importlib.util.find_spec("onnxruntime") is not None


class _FakeEncoding:
    def __init__(self, ids: list[int]) -> None:
        self.ids = ids
        self.attention_mask = [1] * len(ids)


class _FakeTokenizer:
    """Whitespace tokenizer: one id per word plus the EOS (151643), left padded."""

    def encode_batch(self, texts: list[str]) -> list[_FakeEncoding]:
        rows = [[len(word) + 1 for word in text.split()] + [151643] for text in texts]
        width = max(len(r) for r in rows)
        out = []
        for row in rows:
            pad = width - len(row)
            enc = _FakeEncoding([151643] * pad + row)
            enc.attention_mask = [0] * pad + [1] * len(row)
            out.append(enc)
        return out


class _FakeSession:
    """Records feeds; returns hidden states whose last position encodes the row index."""

    def __init__(self) -> None:
        self.feeds: list[dict[str, np.ndarray]] = []

    def run(self, _outputs: Any, feed: dict[str, np.ndarray]) -> list[np.ndarray]:
        self.feeds.append(feed)
        batch, seq = feed["input_ids"].shape
        hidden = np.zeros((batch, seq, _DIM), dtype=np.float32)
        for row in range(batch):
            hidden[row, -1, row % _DIM] = 3.0  # last-token state, deliberately not unit length
            hidden[row, 0, (row + 1) % _DIM] = 99.0  # must be ignored by last-token pooling
        return [hidden]


def _fake_embedder(batch_size: int = 8) -> tuple[QwenOnnxEmbedder, _FakeSession]:
    session = _FakeSession()
    embedder = QwenOnnxEmbedder(session=session, tokenizer=_FakeTokenizer(), batch_size=batch_size)
    return embedder, session


def test_dim_is_1024() -> None:
    assert QwenOnnxEmbedder(session=_FakeSession(), tokenizer=_FakeTokenizer()).dim == _DIM


def test_default_is_one_text_per_model_call_because_int8_couples_batch_rows() -> None:
    assert QwenOnnxEmbedder(session=_FakeSession(), tokenizer=_FakeTokenizer()).batch_size == 1


def test_query_text_follows_the_qwen_instruction_template() -> None:
    text = QwenOnnxEmbedder.format_query("capital of France", task="Find passages")
    assert text == "Instruct: Find passages\nQuery:capital of France"


def test_documents_are_embedded_without_instruction_and_queries_with_it() -> None:
    embedder, _ = _fake_embedder()
    seen: list[str] = []
    real = embedder._tokenizer.encode_batch  # noqa: SLF001 - spy on the injected fake
    embedder._tokenizer.encode_batch = lambda texts: (seen.extend(texts), real(texts))[1]  # type: ignore[method-assign]  # noqa: SLF001
    embedder.embed(["doc one"])
    embedder.embed(["what is x"], query=True)
    assert seen[0] == "doc one"
    assert seen[1].startswith("Instruct: ") and seen[1].endswith("\nQuery:what is x")


def test_last_token_pooling_is_normalised_and_ignores_other_positions() -> None:
    embedder, _ = _fake_embedder()
    vectors = embedder.embed(["a", "b c", "d e f"])
    assert vectors.shape == (3, _DIM)
    assert vectors.dtype == np.float32
    np.testing.assert_allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-6)
    for row in range(3):
        assert vectors[row].argmax() == row  # the 99.0 spike at position 0 was ignored


def test_empty_input_returns_an_empty_matrix_without_running_the_model() -> None:
    embedder, session = _fake_embedder()
    out = embedder.embed([])
    assert out.shape == (0, _DIM)
    assert session.feeds == []


def test_feed_has_position_ids_and_an_empty_kv_cache_for_every_layer() -> None:
    embedder, session = _fake_embedder()
    embedder.embed(["one two", "three"])
    feed = session.feeds[0]
    batch, seq = feed["input_ids"].shape
    assert feed["attention_mask"].shape == (batch, seq)
    # left padding: positions count only real tokens, padding is clamped to 0
    np.testing.assert_array_equal(feed["position_ids"][1], [0, 0, 1])
    for layer in range(_LAYERS):
        for kind in ("key", "value"):
            past = feed[f"past_key_values.{layer}.{kind}"]
            assert past.shape == (batch, 8, 0, 128)
            assert past.dtype == np.float32


def test_long_batches_are_split_by_batch_size() -> None:
    embedder, session = _fake_embedder()
    embedder.batch_size = 2
    out = embedder.embed([f"t{i}" for i in range(5)])
    assert out.shape == (5, _DIM)
    assert [f["input_ids"].shape[0] for f in session.feeds] == [2, 2, 1]


def test_concurrent_embed_calls_are_serialised_and_consistent() -> None:
    embedder, _ = _fake_embedder()
    expected = embedder.embed(["alpha beta"])
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda _: embedder.embed(["alpha beta"]), range(64)))
    for result in results:
        np.testing.assert_array_equal(result, expected)


def test_qwen_onnx_is_a_selectable_backend() -> None:
    settings = Settings(embed_backend="qwen-onnx", embed_model=str(_MODEL_DIR), embed_dim=_DIM)
    assert isinstance(default_embedder(settings), QwenOnnxEmbedder)


def test_backend_dimension_mismatch_is_rejected() -> None:
    settings = Settings(embed_backend="qwen-onnx", embed_model=str(_MODEL_DIR), embed_dim=384)
    with pytest.raises(ValueError, match="1024"):
        default_embedder(settings)


@pytest.mark.skipif(
    not (_HAVE_MODEL and _HAVE_ONNX),
    reason="Qwen3 ONNX int8 files (SWARM_QWEN_ONNX_DIR) or onnxruntime not available",
)
def test_real_model_ranks_the_relevant_passage_first_and_is_batch_invariant() -> None:
    embedder = QwenOnnxEmbedder(model_dir=_MODEL_DIR)
    query = embedder.embed(["What is the capital of France?"], query=True)[0]
    docs = embedder.embed(
        ["Paris is the capital and largest city of France.", "Bananas are yellow fruit."]
    )
    assert docs.shape == (2, _DIM)
    np.testing.assert_allclose(np.linalg.norm(docs, axis=1), 1.0, atol=1e-4)
    assert float(query @ docs[0]) > float(query @ docs[1]) + 0.1
    solo = embedder.embed(["Bananas are yellow fruit."])[0]
    assert float(solo @ docs[1]) > 0.999  # left padding must not change the embedding
