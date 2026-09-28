"""Event-loop and thread-pool helpers."""

from __future__ import annotations

import asyncio
import concurrent.futures
import sys
from collections.abc import Callable

from swarm_sdk.decorators import Static

_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="swarm")


class Runtime:
    """Asyncio integration and blocking work offload."""

    @Static
    def install_uvloop() -> None:
        """Install uvloop as the asyncio policy on platforms that support it."""
        if sys.platform == "win32":
            return
        import uvloop

        uvloop.install()

    @Static
    async def offload[T](fn: Callable[..., T], *args: object) -> T:
        """Run a blocking function on the shared thread pool.

        Args:
            fn: Callable to run off the event loop.
            *args: Positional arguments for ``fn``.

        Returns:
            Result of ``fn(*args)``.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_POOL, fn, *args)


def install_uvloop() -> None:
    """See :meth:`Runtime.install_uvloop`."""
    Runtime.install_uvloop()


async def offload[T](fn: Callable[..., T], *args: object) -> T:
    """See :meth:`Runtime.offload`."""
    return await Runtime.offload(fn, *args)
