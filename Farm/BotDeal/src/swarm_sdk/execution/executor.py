"""Event-loop and thread-pool helpers.

Two global runtime knobs:

* :func:`install_uvloop` swaps the asyncio policy for uvloop (POSIX only), the
  event loop the whole SDK assumes for its concurrent step dispatch.
* :data:`_POOL` is the shared executor that :func:`offload` runs blocking
  provider SDK calls on. Its size adapts to the interpreter build: the
  free-threaded (no-GIL) build of Python 3.14 can actually run 32 blocking
  calls in parallel, while a GIL build gains nothing beyond a modest pool.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import sys
from collections.abc import Callable

from swarm_sdk.execution.concurrency import parallel_cap


def _pool_workers() -> int:
    """Worker count for the shared thread pool, matched to the interpreter build."""
    return parallel_cap()


_POOL = concurrent.futures.ThreadPoolExecutor(
    max_workers=_pool_workers(), thread_name_prefix="swarm"
)


def install_uvloop() -> None:
    """Install uvloop as the asyncio policy on platforms that support it.

    No-op on Windows. Call once at process entrypoint (e.g. ``swarm-grpc``)
    before any event loop is created.
    """
    if sys.platform == "win32":
        return
    import uvloop

    uvloop.install()


async def offload[T](fn: Callable[..., T], *args: object) -> T:
    """Run a blocking function on the shared thread pool.

    Args:
        fn: Synchronous callable (typically a provider SDK call).
        args: Positional arguments for ``fn``.

    Returns:
        The function's result, awaited without blocking the event loop.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_POOL, fn, *args)


__all__ = ["install_uvloop", "offload"]
