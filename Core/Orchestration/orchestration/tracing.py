"""LangSmith tracing switch. Reads the environment only; never stores a key."""

from __future__ import annotations

import os


def tracing_enabled() -> bool:
    """Return True when LangSmith tracing is switched on and a key is present.

    Returns:
        True if ``LANGSMITH_TRACING`` is ``"true"`` (any case) and
        ``LANGSMITH_API_KEY`` is non-empty after stripping whitespace.
    """
    flag = os.environ.get("LANGSMITH_TRACING", "").strip().lower() == "true"
    key = os.environ.get("LANGSMITH_API_KEY", "").strip()
    return flag and bool(key)
