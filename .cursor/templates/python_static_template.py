"""Python Static Template — Swarm (PEP 810–ready).

Agent contract (coding assistants):
  Read callers, tests, and config before editing.
  One failed attempt → analyse root cause → one deliberate fix (no retry loops).
  Profile before optimizing hot paths; measure before/after (Optimizer norms).
  Delete unused role sections when copying; no import-time side effects.
  Parallel swarm steps: disjoint ``files`` per sibling agent; cap via ``CoworkRole``.
  In ``src/swarm_sdk/``: use ``swarm_sdk.execution`` for caps.

Copy this skeleton when starting a new module under ``src/swarm_sdk/``.
Delete unused role sections. Keep roles grouped; do not interleave unrelated helpers.

Layout:

1. Module docstring, then **always** ``from __future__ import annotations`` (first statement)
2. Stdlib / third-party / local imports (no import-time side effects)
3. ``@wrappers`` — reusable decorators
4. Role classes — ``Type``, ``Hint``, ``Vect``, ``Math``, ``Db``, ``Batch``, ``Cowork``, …
5. Role functions — same order as classes (``loop_*`` aliases for ``batch_*``)
6. ``__all__`` + optional ``main`` under ``__main__`` only

PEP 810 (Explicit lazy imports, Python 3.15+): defer heavy deps; ``TYPE_CHECKING`` for types.
PEP 703 free-threaded 3.14: ``CoworkRole`` / ``swarm_sdk.execution.parallel_cap``.

Canonical source: ``.cursor/templates/python_static_template.py``.
Lite: ``python_static_template_lite.py``.
Ops: root ``AGENTS.md`` → Topic: Python Static Template. Do not import this file from runtime code.
"""

# ALWAYS: first statement after the module docstring — before any other import.
from __future__ import annotations

import functools
import os
import sys
import time
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Annotated, Any, ParamSpec, Protocol, TypeVar

if TYPE_CHECKING:
    pass

# =============================================================================
# Python Static Template
# =============================================================================

P = ParamSpec("P")
R = TypeVar("R")
T = TypeVar("T")

type Vec = Sequence[float]
type Matrix = Sequence[Sequence[float]]
type RowId = Annotated[int, "primary key"]

_DEFAULT_TRANSIENT: tuple[type[BaseException], ...] = (
    TimeoutError,
    OSError,
    ConnectionError,
)


class wrappers:
    """Static namespace for decorator factories. Prefer `@wrappers.name`."""

    @staticmethod
    def timed(fn: Callable[P, R]) -> Callable[P, R]:
        """Record wall time only when ``SWARM_PROFILE`` is set (not for hot paths)."""
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
    def logged(fn: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(fn)
        def _inner(*args: P.args, **kwargs: P.kwargs) -> R:
            return fn(*args, **kwargs)

        return _inner

    @staticmethod
    def retry_transient(
        times: int = 2,
        on: tuple[type[BaseException], ...] = _DEFAULT_TRANSIENT,
    ) -> Callable[[Callable[P, R]], Callable[P, R]]:
        """Retry only on transient errors — never on validation or logic bugs."""

        def _decorate(fn: Callable[P, R]) -> Callable[P, R]:
            @functools.wraps(fn)
            def _inner(*args: P.args, **kwargs: P.kwargs) -> R:
                last: BaseException | None = None
                attempts = max(times, 1)
                for _ in range(attempts):
                    try:
                        return fn(*args, **kwargs)
                    except on as exc:
                        last = exc
                if last is not None:
                    raise last
                return fn(*args, **kwargs)

            return _inner

        return _decorate

    @staticmethod
    def retry(times: int = 1) -> Callable[[Callable[P, R]], Callable[P, R]]:
        """Alias for :meth:`retry_transient` (prefer ``retry_transient`` explicitly)."""
        return wrappers.retry_transient(times=times)


class TypeRole:
    class SupportsClose(Protocol):
        def close(self) -> None: ...

    @staticmethod
    def ensure_str(value: object) -> str:
        if not isinstance(value, str):
            raise TypeError(f"expected str, got {type(value).__name__}")
        return value


@dataclass(frozen=True, slots=True)
class HintRole:
    name: str
    description: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

    def as_annotated(self) -> Any:
        return Annotated[str, self]


@dataclass(slots=True)
class VectRole:
    dim: int

    def zeros(self) -> list[float]:
        return [0.0] * self.dim

    def dot(self, a: Vec, b: Vec) -> float:
        if len(a) != len(b):
            raise ValueError("vector length mismatch")
        return sum(x * y for x, y in zip(a, b, strict=True))


class MathRole:
    @staticmethod
    def clamp(x: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, x))

    @staticmethod
    def mean(xs: Iterable[float]) -> float:
        total = 0.0
        n = 0
        for x in xs:
            total += x
            n += 1
        if n == 0:
            raise ValueError("empty sequence")
        return total / n


@dataclass(slots=True)
class DbRole:
    path: str
    _open: bool = False

    def connect(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    @wrappers.logged
    def get(self, key: str) -> bytes | None:
        if not self._open:
            raise RuntimeError("db not connected")
        _ = key
        return None


class CoworkRole:
    """Sketch — in ``src/swarm_sdk`` import ``swarm_sdk.execution`` instead."""

    @staticmethod
    def gil_enabled() -> bool:
        try:
            return sys._is_gil_enabled()
        except AttributeError:
            return True

    @staticmethod
    def parallel_cap() -> int:
        return 8 if CoworkRole.gil_enabled() else 32


class BatchRole:
    """Bounded batch / async helpers (not unbounded loops)."""

    @staticmethod
    async def gather_limited[T](
        coros: Sequence[Awaitable[T]],
        *,
        limit: int | None = None,
    ) -> list[T]:
        import asyncio

        cap = limit if limit is not None else CoworkRole.parallel_cap()
        sem = asyncio.Semaphore(max(cap, 1))
        results: list[T] = []

        async def _one(aw: Awaitable[T]) -> None:
            async with sem:
                results.append(await aw)

        async with asyncio.TaskGroup() as tg:
            for aw in coros:
                tg.create_task(_one(aw))
        return results


LoopRole = BatchRole


def type_is_mapping(value: object) -> bool:
    return isinstance(value, dict)


def hint_tag(*tags: str) -> HintRole:
    return HintRole(name="tag", tags=tags)


@wrappers.timed
def vect_l2(a: Vec, b: Vec) -> float:
    if len(a) != len(b):
        raise ValueError("vector length mismatch")
    return sum((x - y) ** 2 for x, y in zip(a, b, strict=True)) ** 0.5


def math_safe_div(num: float, den: float, default: float = 0.0) -> float:
    if den == 0.0:
        return default
    return num / den


def db_uri(path: str, *, read_only: bool = False) -> str:
    mode = "mode=ro" if read_only else "mode=rwc"
    return f"file:{path}?{mode}"


def batch_chunked[T](items: Sequence[T], size: int) -> list[Sequence[T]]:
    if size < 1:
        raise ValueError("size must be >= 1")
    return [items[i : i + size] for i in range(0, len(items), size)]


def loop_chunked[T](items: Sequence[T], size: int) -> list[Sequence[T]]:
    return batch_chunked(items, size)


def cowork_gil_enabled() -> bool:
    try:
        from swarm_sdk.execution import gil_enabled as sdk_gil

        return sdk_gil()
    except ImportError:
        return CoworkRole.gil_enabled()


def cowork_parallel_cap() -> int:
    try:
        from swarm_sdk.execution import parallel_cap as sdk_cap

        return sdk_cap()
    except ImportError:
        return CoworkRole.parallel_cap()


__all__ = [
    "wrappers",
    "TypeRole",
    "HintRole",
    "VectRole",
    "MathRole",
    "DbRole",
    "BatchRole",
    "LoopRole",
    "CoworkRole",
    "type_is_mapping",
    "hint_tag",
    "vect_l2",
    "math_safe_div",
    "db_uri",
    "batch_chunked",
    "loop_chunked",
    "cowork_gil_enabled",
    "cowork_parallel_cap",
]


def main() -> int:
    """Smoke + Optimizer-style cap check (profile hot paths with ``SWARM_PROFILE=1``)."""
    v = VectRole(dim=3)
    assert MathRole.clamp(v.dot([1, 0, 0], [1, 0, 0]), 0.0, 1.0) == 1.0
    assert loop_chunked([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]
    cap = cowork_parallel_cap()
    assert cap in (8, 32)
    from swarm_sdk.execution import parallel_cap as sdk_cap

    assert cap == sdk_cap()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
