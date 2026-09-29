"""Python Static Template — Swarm (PEP 810–ready).

Copy this skeleton when starting a new module under ``src/swarm_sdk/``.
Delete unused role sections. Keep roles grouped; do not interleave unrelated helpers.

Layout:

1. Module docstring, then **always** ``from __future__ import annotations`` (first statement)
2. Stdlib / third-party / local imports (no import-time side effects)
3. ``@wrappers`` — reusable decorators
4. Role classes — ``Type``, ``Hint``, ``Vect``, ``Math``, ``Db``, ``Loop``, …
5. Role functions — same order as classes
6. ``__all__`` + optional ``main`` under ``__main__`` only

PEP 810 (Explicit lazy imports, Python 3.15+): keep this module free of
import-time side effects so it stays ``lazy import``–eligible. On 3.14,
defer heavy optional deps inside the functions that need them; use
``TYPE_CHECKING`` for type-only imports.

Free-threaded Python 3.14 (PEP 703): use :class:`CoworkRole` caps so parallel swarm
agents (disjoint files per wave) scale on no-GIL builds without oversubscribing
on GIL builds. Matches ``swarm_sdk.execution.executor`` pool sizing.

Canonical copy also lives in root ``AGENTS.md`` → Topic: Python Static Template.
Do not import this file from runtime package code — copy and trim.
"""

# ALWAYS: first statement after the module docstring — before any other import.
from __future__ import annotations

import functools
import sys
import time
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Annotated, Any, ParamSpec, Protocol, TypeVar

if TYPE_CHECKING:
    # Type-only imports stay here (PEP 649/749 + PEP 810–friendly).
    pass

# =============================================================================
# Python Static Template
# =============================================================================
# Topic map (root ``AGENTS.md`` → Topic: Python Static Template):
#   Subtopic: type aliases & typevars
#   Subtopic: wrappers
#   Subtopic: role classes (Type → Hint → Vect → Math → Db → Loop → Cowork)
#   Subtopic: role functions (same order)
#   Subtopic: free-threading & agent cowork (CoworkRole / cowork_*)
#   Subtopic: public surface (+ ``main`` smoke under ``__main__`` only)
# =============================================================================

# --- Python Static Template — type aliases & typevars -----------------------
# Python 3.12+ ``type`` statement; shared by roles
# -----------------------------------------------------------------------------

P = ParamSpec("P")
R = TypeVar("R")
T = TypeVar("T")

type Vec = Sequence[float]
type Matrix = Sequence[Sequence[float]]
type RowId = Annotated[int, "primary key"]


# --- Python Static Template — wrappers --------------------------------------
# Decorators: @wrappers.timed, @wrappers.logged, @wrappers.retry(n)
# -----------------------------------------------------------------------------


class wrappers:
    """Static namespace for decorator factories. Prefer `@wrappers.name`."""

    @staticmethod
    def timed(fn: Callable[P, R]) -> Callable[P, R]:
        """Record wall time on ``fn.__name__`` (no I/O at decoration time)."""

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
        """Preserve signature; hook for structured logging later."""

        @functools.wraps(fn)
        def _inner(*args: P.args, **kwargs: P.kwargs) -> R:
            return fn(*args, **kwargs)

        return _inner

    @staticmethod
    def retry(times: int = 1) -> Callable[[Callable[P, R]], Callable[P, R]]:
        """Retry sync call ``times`` times on any Exception."""

        def _decorate(fn: Callable[P, R]) -> Callable[P, R]:
            @functools.wraps(fn)
            def _inner(*args: P.args, **kwargs: P.kwargs) -> R:
                last: Exception | None = None
                for _ in range(max(times, 1)):
                    try:
                        return fn(*args, **kwargs)
                    except Exception as exc:  # noqa: BLE001 — template boundary
                        last = exc
                assert last is not None
                raise last

            return _inner

        return _decorate


# --- Python Static Template — role classes ----------------------------------
# One concern per class; keep methods thin
# -----------------------------------------------------------------------------


# --- type -------------------------------------------------------------------


class TypeRole:
    """Structural typing helpers (Protocols, narrowers)."""

    class SupportsClose(Protocol):
        def close(self) -> None: ...

    @staticmethod
    def ensure_str(value: object) -> str:
        if not isinstance(value, str):
            raise TypeError(f"expected str, got {type(value).__name__}")
        return value


# --- hint -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HintRole:
    """Annotation / metadata carriers for APIs and schemas."""

    name: str
    description: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

    def as_annotated(self) -> Any:
        return Annotated[str, self]


# --- vect -------------------------------------------------------------------


@dataclass(slots=True)
class VectRole:
    """Vector ops surface (CPU path; swap for GPU backends in real modules)."""

    dim: int

    def zeros(self) -> list[float]:
        return [0.0] * self.dim

    def dot(self, a: Vec, b: Vec) -> float:
        if len(a) != len(b):
            raise ValueError("vector length mismatch")
        return sum(x * y for x, y in zip(a, b, strict=True))


# --- math -------------------------------------------------------------------


class MathRole:
    """Scalar / reduction math (no I/O)."""

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


# --- db ---------------------------------------------------------------------


@dataclass(slots=True)
class DbRole:
    """DB / store façade — connect explicitly; never open at import time."""

    path: str
    _open: bool = False

    def connect(self) -> None:
        """Eager open — call from app startup, not at import (PEP 810)."""
        self._open = True

    def close(self) -> None:
        self._open = False

    @wrappers.logged
    def get(self, key: str) -> bytes | None:
        if not self._open:
            raise RuntimeError("db not connected")
        _ = key
        return None


# --- cowork (free-threading) ------------------------------------------------


class CoworkRole:
    """Parallel agent / step caps for GIL vs free-threaded Python 3.14+ (PEP 703)."""

    @staticmethod
    def gil_enabled() -> bool:
        """Return whether the GIL is enabled (``True`` on normal 3.14 builds)."""
        try:
            return sys._is_gil_enabled()
        except AttributeError:
            return True

    @staticmethod
    def parallel_cap() -> int:
        """Default concurrency cap: conservative on GIL, wider on free-threaded builds."""
        return 8 if CoworkRole.gil_enabled() else 32


# --- loop -------------------------------------------------------------------


class LoopRole:
    """Async / batch loop helpers."""

    @staticmethod
    async def gather_limited[T](
        coros: Sequence[Awaitable[T]],
        *,
        limit: int | None = None,
    ) -> list[T]:
        """Run awaitables with a concurrency cap (defaults to :meth:`CoworkRole.parallel_cap`)."""
        import asyncio  # deferred: only needed when this helper runs

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


# --- Python Static Template — role functions --------------------------------
# Free functions; same role order as classes
# -----------------------------------------------------------------------------


# --- type -------------------------------------------------------------------


def type_is_mapping(value: object) -> bool:
    return isinstance(value, dict)


# --- hint -------------------------------------------------------------------


def hint_tag(*tags: str) -> HintRole:
    return HintRole(name="tag", tags=tags)


# --- vect -------------------------------------------------------------------


@wrappers.timed
def vect_l2(a: Vec, b: Vec) -> float:
    if len(a) != len(b):
        raise ValueError("vector length mismatch")
    return sum((x - y) ** 2 for x, y in zip(a, b, strict=True)) ** 0.5


# --- math -------------------------------------------------------------------


def math_safe_div(num: float, den: float, default: float = 0.0) -> float:
    if den == 0.0:
        return default
    return num / den


# --- db ---------------------------------------------------------------------


def db_uri(path: str, *, read_only: bool = False) -> str:
    mode = "mode=ro" if read_only else "mode=rwc"
    return f"file:{path}?{mode}"


# --- loop -------------------------------------------------------------------


def loop_chunked[T](items: Sequence[T], size: int) -> list[Sequence[T]]:
    if size < 1:
        raise ValueError("size must be >= 1")
    return [items[i : i + size] for i in range(0, len(items), size)]


# --- cowork -----------------------------------------------------------------


def cowork_gil_enabled() -> bool:
    return CoworkRole.gil_enabled()


def cowork_parallel_cap() -> int:
    return CoworkRole.parallel_cap()


# --- Python Static Template — public surface --------------------------------
# Explicit ``__all__``; smoke via ``main()`` only when run as ``__main__``
# -----------------------------------------------------------------------------

__all__ = [
    "wrappers",
    "TypeRole",
    "HintRole",
    "VectRole",
    "MathRole",
    "DbRole",
    "LoopRole",
    "CoworkRole",
    "type_is_mapping",
    "hint_tag",
    "vect_l2",
    "math_safe_div",
    "db_uri",
    "loop_chunked",
    "cowork_gil_enabled",
    "cowork_parallel_cap",
]


def main() -> int:
    """Smoke the template locally: ``uv run python .cursor/templates/python_static_template.py``."""
    v = VectRole(dim=3)
    assert MathRole.clamp(v.dot([1, 0, 0], [1, 0, 0]), 0.0, 1.0) == 1.0
    assert loop_chunked([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
