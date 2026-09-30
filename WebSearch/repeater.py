"""Sync retry helper. Use ``@repeater.s`` or ``@repeater.s(times=3)`` on I/O."""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import ParamSpec, TypeVar, overload

P = ParamSpec("P")
R = TypeVar("R")

_TRANSIENT: tuple[type[BaseException], ...] = (TimeoutError, OSError, ConnectionError)


class _Repeater:
    @overload
    def s(self, fn: Callable[P, R]) -> Callable[P, R]: ...

    @overload
    def s(
        self,
        fn: None = None,
        *,
        times: int = 2,
        on: tuple[type[BaseException], ...] = _TRANSIENT,
    ) -> Callable[[Callable[P, R]], Callable[P, R]]: ...

    def s(
        self,
        fn: Callable[P, R] | None = None,
        *,
        times: int = 2,
        on: tuple[type[BaseException], ...] = _TRANSIENT,
    ) -> Callable[P, R] | Callable[[Callable[P, R]], Callable[P, R]]:
        """Retry *times* on transient errors (``TimeoutError``, ``OSError``, ``ConnectionError``).

        Args:
            fn (Callable | None): Decorated function when used as ``@repeater.s``.
            times (int): Attempts, including the first try.
            on (tuple[type[BaseException], ...]): Exceptions that retry.

        Returns:
            Callable: Wrapped function, or a decorator if ``fn`` is omitted.
        """

        def decorate(func: Callable[P, R]) -> Callable[P, R]:
            @functools.wraps(func)
            def inner(*args: P.args, **kwargs: P.kwargs) -> R:
                last: BaseException | None = None
                for _ in range(max(times, 1)):
                    try:
                        return func(*args, **kwargs)
                    except on as exc:
                        last = exc
                if last is not None:
                    raise last
                return func(*args, **kwargs)

            return inner

        if fn is not None:
            return decorate(fn)
        return decorate


repeater = _Repeater()

__all__ = ["repeater"]
