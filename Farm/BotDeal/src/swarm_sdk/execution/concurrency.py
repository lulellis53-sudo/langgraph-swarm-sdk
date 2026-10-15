"""GIL / free-threading concurrency caps for pools and orchestrator waves."""

from __future__ import annotations

import sys

GIL_POOL_WORKERS = 8
FREE_THREADED_POOL_WORKERS = 32


def gil_enabled() -> bool:
    """Return whether the GIL is enabled (``True`` on standard CPython builds)."""
    try:
        return sys._is_gil_enabled()
    except AttributeError:
        return True


def parallel_cap() -> int:
    """Default parallel worker / wave cap for this interpreter build."""
    return GIL_POOL_WORKERS if gil_enabled() else FREE_THREADED_POOL_WORKERS


__all__ = [
    "FREE_THREADED_POOL_WORKERS",
    "GIL_POOL_WORKERS",
    "gil_enabled",
    "parallel_cap",
]
