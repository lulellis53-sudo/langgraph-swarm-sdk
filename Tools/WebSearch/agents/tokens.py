"""Token budgets: tiktoken (LLM prompt) and Qwen3-Embedding int8 tokenizer.

``count_tokens`` is the conservative packer: max of both counters so a brief
never overruns the model *or* the embedder.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path

_ENCODING_NAME = "cl100k_base"
_DEFAULT_QWEN_DIR = Path.home() / "build" / "qwen3-embed"


def qwen_tokenizer_path() -> Path | None:
    """Path to Qwen3-Embedding ``tokenizer.json`` when the int8 ONNX tree is present."""
    raw = os.environ.get("SWARM_QWEN_ONNX_DIR")
    roots = [Path(raw).expanduser()] if raw else []
    roots.append(_DEFAULT_QWEN_DIR)
    for root in roots:
        tok = root / "tokenizer.json"
        if tok.is_file():
            return tok
    return None


@functools.cache
def _tiktoken_encoding() -> object | None:
    try:
        import tiktoken
    except ImportError:
        return None
    try:
        return tiktoken.get_encoding(_ENCODING_NAME)
    except Exception:
        return None


@functools.cache
def _qwen_tokenizer() -> object | None:
    path = qwen_tokenizer_path()
    if path is None:
        return None
    try:
        from tokenizers import Tokenizer
    except ImportError:
        return None
    tokenizer = Tokenizer.from_file(str(path))
    tokenizer.no_truncation()
    tokenizer.no_padding()
    return tokenizer


def count_tiktoken(text: str) -> int:
    """Count tokens with tiktoken ``cl100k_base`` (LLM prompt cost)."""
    if not text:
        return 0
    encoding = _tiktoken_encoding()
    if encoding is None:
        return max(1, len(text) // 4)
    return len(encoding.encode(text, disallowed_special=()))


def count_embedder(text: str) -> int:
    """Count tokens with the Qwen3-Embedding-0.6B int8 tokenizer when installed."""
    if not text:
        return 0
    tokenizer = _qwen_tokenizer()
    if tokenizer is None:
        return count_tiktoken(text)
    encoded = tokenizer.encode(text)
    ids = getattr(encoded, "ids", encoded)
    return len(ids)


def count_tokens(text: str) -> int:
    """Packer budget: the larger of tiktoken and the Qwen int8 tokenizer."""
    if not text:
        return 0
    return max(count_tiktoken(text), count_embedder(text))
