"""Event-loop and thread-pool helpers."""

from __future__ import annotations

import asyncio
import concurrent.futures
import sys
from collections.abc import Callable

_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="swarm")


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
