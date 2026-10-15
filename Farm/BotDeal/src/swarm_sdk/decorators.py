"""Project decorators: ``@wrapper`` for pure helpers, ``@Static`` for class utilities."""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import Any, cast


def wrapper[F: Callable[..., Any]](func: F) -> F:
    """Mark a side-effect-free helper (preserves metadata for tooling and docs).

    Args:
        func: Callable to wrap.

    Returns:
        The same callable with ``__wrapped__`` metadata preserved.
    """
    return cast(F, functools.wraps(func)(func))


def Static[F: Callable[..., Any]](func: F) -> staticmethod:
    """Project alias for ``@staticmethod`` on class utility methods.

    Args:
        func: Method that does not use ``self`` or ``cls``.

    Returns:
        A static method descriptor.
    """
    return staticmethod(func)


def async_wrapper(func: Callable[..., Any]) -> Callable[..., Awaitable[Any]]:
    """Run a sync callable on the shared executor via ``runtime.offload``.

    Args:
        func: Blocking function to expose as async.

    Returns:
        Async function that awaits ``offload(func, ...)`.
    """

    @functools.wraps(func)
    async def inner(*args: Any, **kwargs: Any) -> Any:
        from swarm_sdk.execution.executor import offload

        return await offload(lambda: func(*args, **kwargs))

    return inner


__all__ = ["Static", "async_wrapper", "wrapper"]
