"""Text preprocessing helpers for retrieval and keyword indexing."""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Extract lowercased alphanumeric tokens from text.

    Args:
        text: Raw input string.

    Returns:
        List of ``[a-z0-9]+`` tokens in encounter order.
    """
    return _TOKEN_RE.findall(text.lower())


__all__ = ["tokenize"]
