"""Python Static Template (lite) — minimal scaffold for small ``src/swarm_sdk/`` modules.

Agent contract: read callers/tests first; one deliberate fix; no blind retries.
Always ``from __future__ import annotations`` immediately after this docstring.

Full template: ``.cursor/templates/python_static_template.py``.
"""

# ALWAYS: first statement after the module docstring.
from __future__ import annotations

import functools
import os
import sys
import time
from collections.abc import Callable
from typing import ParamSpec, Protocol, TypeVar

P = ParamSpec("P")
R = TypeVar("R")

_DEFAULT_TRANSIENT: tuple[type[BaseException], ...] = (
    TimeoutError,
    OSError,
    ConnectionError,
)


class wrappers:
    @staticmethod
    def timed(fn: Callable[P, R]) -> Callable[P, R]:
        if not os.environ.get("SWARM_PROFILE"):
            return fn

        @functools.wraps(fn)
        def _inner(*args: P.args, **kwargs: P.kwargs) -> R:
            start = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                _ = time.perf_counter() - start

        return _inner

    @staticmethod
    def retry_transient(
        times: int = 2,
        on: tuple[type[BaseException], ...] = _DEFAULT_TRANSIENT,
    ) -> Callable[[Callable[P, R]], Callable[P, R]]:
        def _decorate(fn: Callable[P, R]) -> Callable[P, R]:
            @functools.wraps(fn)
            def _inner(*args: P.args, **kwargs: P.kwargs) -> R:
                last: BaseException | None = None
                for _ in range(max(times, 1)):
                    try:
                        return fn(*args, **kwargs)
                    except on as exc:
                        last = exc
                if last is not None:
                    raise last
                return fn(*args, **kwargs)

            return _inner

        return _decorate


class TypeRole:
    class SupportsClose(Protocol):
        def close(self) -> None: ...

    @staticmethod
    def ensure_str(value: object) -> str:
        if not isinstance(value, str):
            raise TypeError(f"expected str, got {type(value).__name__}")
        return value


class CoworkRole:
    @staticmethod
    def gil_enabled() -> bool:
        try:
            return sys._is_gil_enabled()
        except AttributeError:
            return True

    @staticmethod
    def parallel_cap() -> int:
        return 8 if CoworkRole.gil_enabled() else 32


def type_is_mapping(value: object) -> bool:
    return isinstance(value, dict)


def cowork_parallel_cap() -> int:
    try:
        from swarm_sdk.execution import parallel_cap

        return parallel_cap()
    except ImportError:
        return CoworkRole.parallel_cap()


__all__ = [
    "wrappers",
    "TypeRole",
    "CoworkRole",
    "type_is_mapping",
    "cowork_parallel_cap",
]


def main() -> int:
    assert type_is_mapping({})
    cap = cowork_parallel_cap()
    assert cap in (8, 32)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
