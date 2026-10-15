"""Token packer: tiktoken cl100k_base and Qwen3-Embedding int8 tokenizer."""

from __future__ import annotations

from WebSearch.Core.agents.tokens import (
    count_embedder,
    count_tiktoken,
    count_tokens,
    qwen_tokenizer_path,
)


def test_empty_is_zero() -> None:
    assert count_tokens("") == 0
    assert count_tiktoken("") == 0
    assert count_embedder("") == 0


def test_packer_is_max_of_both_counters() -> None:
    text = "LangGraph swarm handoffs with a packed brief"
    packed = count_tokens(text)
    assert packed == max(count_tiktoken(text), count_embedder(text))
    assert packed > 0


def test_qwen_int8_tokenizer_when_onnx_tree_is_present() -> None:
    path = qwen_tokenizer_path()
    if path is None:
        assert count_embedder("hello") == count_tiktoken("hello")
        return
    assert path.name == "tokenizer.json"
    assert count_embedder("Qwen3-Embedding int8 tokenizer.json") > 0
