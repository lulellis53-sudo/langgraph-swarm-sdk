"""GIL / free-threading concurrency caps for pools and orchestrator waves."""

from __future__ import annotations

GIL_POOL_WORKERS = 8
FREE_THREADED_POOL_WORKERS = 32


def parallel_cap() -> int:
    """Default parallel worker / wave cap for this interpreter build."""
    # Lazy import: the audited GIL probe lives in the package __init__.
    from swarm_sdk.execution import gil_enabled

    return GIL_POOL_WORKERS if gil_enabled() else FREE_THREADED_POOL_WORKERS


__all__ = [
    "FREE_THREADED_POOL_WORKERS",
    "GIL_POOL_WORKERS",
    "parallel_cap",
]
