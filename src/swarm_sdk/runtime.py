"""Event-loop and thread-pool helpers."""

from __future__ import annotations

import asyncio
import concurrent.futures
import sys
from collections.abc import Callable


def _pool_workers() -> int:
    """Free-threaded Python (3.14 no-GIL) can saturate many blocking calls at
    once; the GIL build keeps a modest pool."""
    try:
        if sys._is_gil_enabled():
            return 8
    except AttributeError:
        pass
    return 32


_POOL = concurrent.futures.ThreadPoolExecutor(
    max_workers=_pool_workers(), thread_name_prefix="swarm"
)


def install_uvloop() -> None:
    """Install uvloop as the asyncio policy on platforms that support it."""
    if sys.platform == "win32":
        return
    import uvloop

    uvloop.install()


async def offload[T](fn: Callable[..., T], *args: object) -> T:
    """Run a blocking function on the shared thread pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_POOL, fn, *args)
