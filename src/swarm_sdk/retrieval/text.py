"""Text preprocessing helpers for retrieval and keyword indexing."""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Extract lowercased alphanumeric tokens from text."""
    return _TOKEN_RE.findall(text.lower())


__all__ = ["tokenize"]
