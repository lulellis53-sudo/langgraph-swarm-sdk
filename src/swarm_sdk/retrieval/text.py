"""Text preprocessing helpers for retrieval and keyword indexing."""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Extract lowercased alphanumeric tokens from text."""
    return _TOKEN_RE.findall(text.lower())


def tokenize_zero_copy(text: str) -> list[str]:
    """Zero-copy extraction of lowercased alphanumeric tokens from text using memoryviews."""
    encoded = text.lower().encode("utf-8")
    view = memoryview(encoded)
    tokens: list[str] = []
    start = None
    for idx, byte in enumerate(view):
        is_alnum = (48 <= byte <= 57) or (97 <= byte <= 122)
        if is_alnum and start is None:
            start = idx
        elif not is_alnum and start is not None:
            tokens.append(bytes(view[start:idx]).decode("utf-8"))
            start = None
    if start is not None:
        tokens.append(bytes(view[start:]).decode("utf-8"))
    return tokens


__all__ = ["tokenize", "tokenize_zero_copy"]
