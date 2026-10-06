"""Python Static Template — Swarm agents (PEP 810–ready).

One scaffold for every agent module. Its public surface is **eleven** pure functions, grouped
by role prefix; copy the file, keep the roles you use, delete the rest.

    type_is_mapping   type_ensure_str                    narrow untrusted values
    hint_tag                                             annotation metadata
    vect_dot          vect_l2                            vector math (no numpy needed)
    math_clamp        math_safe_div                      scalar reductions (no I/O)
    db_uri                                               SQLite URI for a path
    batch_chunked                                        bounded batches
    cowork_gil_enabled  cowork_parallel_cap              PEP 703 caps for sibling agents

Agent contract (coding assistants):
  Read callers, tests, and config before editing.
  One failed attempt → analyse root cause → one deliberate fix (no retry loops).
  Profile before optimizing hot paths; measure before/after (Optimizer norms).
  No import-time side effects; heavy deps go inside the function that needs them.
  Never log secrets, tokens or full request bodies.
  Parallel swarm steps: disjoint ``files`` per sibling agent; cap via ``cowork_parallel_cap``.
  In ``src/swarm_sdk/``: use ``swarm_sdk.execution.concurrency`` for caps.

Layout:

1. Module docstring, then **always** ``from __future__ import annotations`` (first statement)
2. Stdlib / third-party / local imports, ``logger``
3. ``wrappers`` — reusable decorators (``timed``, ``logged``, ``retry_transient``)
4. Role classes — state-holding only: ``Type``, ``Hint``, ``Vect``, ``Db``, ``Batch``, ``Cowork``
5. Role functions — the eleven above
6. ``__all__`` + ``main`` smoke under ``__main__`` only

PEP 810 (Explicit lazy imports, Python 3.15+): defer heavy deps; ``TYPE_CHECKING`` for types.
PEP 703 free-threaded 3.14: ``swarm_sdk.execution.concurrency.parallel_cap``.

Canonical source: ``.cursor/templates/python_static_template.py``.
Lite: ``python_static_template_lite.py``.
Ops: root ``AGENTS.md`` → Topic: Python Static Template. Do not import this file from runtime code.
"""

# ALWAYS: first statement after the module docstring — before any other import.
from __future__ import annotations

import asyncio
import functools
import logging
import math
import os
import sys
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Annotated, Any, Protocol, Self, TypeGuard, cast

logger = logging.getLogger(__name__)

# =============================================================================
# Python Static Template
# =============================================================================

type Vec = Sequence[float]
type Matrix = Sequence[Sequence[float]]
type RowId = Annotated[int, "primary key"]

_DEFAULT_TRANSIENT: tuple[type[BaseException], ...] = (
    TimeoutError,
    OSError,
    ConnectionError,
)
GIL_PARALLEL_CAP = 8
FREE_THREADED_PARALLEL_CAP = 32


def _name(fn: Callable[..., object]) -> str:
    """Return a printable name for any callable (``functools.partial`` has no ``__qualname__``)."""
    return getattr(fn, "__qualname__", repr(fn))


class wrappers:
    """Static namespace for decorator factories. Prefer ``@wrappers.name``."""

    @staticmethod
    def timed[**P, R](fn: Callable[P, R]) -> Callable[P, R]:
        """Log wall time at DEBUG only when ``SWARM_PROFILE`` is set (not for hot paths)."""
        if not os.environ.get("SWARM_PROFILE"):
            return fn

        @functools.wraps(fn)
        def _inner(*args: P.args, **kwargs: P.kwargs) -> R:
            start = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                logger.debug("%s took %.6fs", _name(fn), time.perf_counter() - start)

        return _inner

    @staticmethod
    def logged[**P, R](fn: Callable[P, R]) -> Callable[P, R]:
        """Log calls at DEBUG (names only, never arguments); the caller owns error logging."""

        @functools.wraps(fn)
        def _inner(*args: P.args, **kwargs: P.kwargs) -> R:
            logger.debug("call %s", _name(fn))
            return fn(*args, **kwargs)

        return _inner

    @staticmethod
    def retry_transient[**P, R](
        times: int = 2,
        on: tuple[type[BaseException], ...] = _DEFAULT_TRANSIENT,
    ) -> Callable[[Callable[P, R]], Callable[P, R]]:
        """Retry only on transient errors, ``times`` attempts in total.

        Never use it for validation or logic bugs. The last attempt is not guarded, so its
        exception reaches the caller with its original traceback.
        """

        def _decorate(fn: Callable[P, R]) -> Callable[P, R]:
            @functools.wraps(fn)
            def _inner(*args: P.args, **kwargs: P.kwargs) -> R:
                attempts = max(times, 1)
                for attempt in range(1, attempts):
                    try:
                        return fn(*args, **kwargs)
                    except on as exc:
                        logger.warning(
                            "%s failed (attempt %d/%d): %s", _name(fn), attempt, attempts, exc
                        )
                return fn(*args, **kwargs)

            return _inner

        return _decorate


class TypeRole:
    class SupportsClose(Protocol):
        def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class HintRole:
    name: str
    description: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

    def as_annotated(self) -> Any:
        return Annotated[str, self]


@dataclass(slots=True)
class VectRole:
    """Fixed-dimension vector helper; pure math lives in ``vect_*``."""

    dim: int

    def zeros(self) -> list[float]:
        return [0.0] * self.dim

    def dot(self, a: Vec, b: Vec) -> float:
        if len(a) != self.dim or len(b) != self.dim:
            raise ValueError(f"expected dimension {self.dim}")
        return vect_dot(a, b)


@dataclass(slots=True)
class DbRole:
    """Store façade: connect/close once, usable as a context manager."""

    path: str
    _open: bool = field(default=False, init=False)

    def connect(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    def __enter__(self) -> Self:
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        del exc_type, exc, tb
        self.close()

    @wrappers.logged
    def get(self, key: str) -> bytes | None:
        if not self._open:
            raise RuntimeError("db not connected")
        _ = key
        return None


class CoworkRole:
    """Sketch — in ``src/swarm_sdk`` import ``swarm_sdk.execution.concurrency`` instead."""

    @staticmethod
    def gil_enabled() -> bool:
        probe = getattr(sys, "_is_gil_enabled", None)
        return True if probe is None else bool(probe())

    @staticmethod
    def parallel_cap() -> int:
        return GIL_PARALLEL_CAP if CoworkRole.gil_enabled() else FREE_THREADED_PARALLEL_CAP


class BatchRole:
    """Bounded batch / async helpers (not unbounded loops)."""

    @staticmethod
    async def gather_limited[T](
        coros: Sequence[Awaitable[T]],
        *,
        limit: int | None = None,
    ) -> list[T]:
        """Await ``coros`` with at most ``limit`` in flight; results keep input order."""
        cap = limit if limit is not None else cowork_parallel_cap()
        sem = asyncio.Semaphore(max(cap, 1))
        results: list[T | None] = [None] * len(coros)

        async def _one(index: int, aw: Awaitable[T]) -> None:
            async with sem:
                results[index] = await aw

        async with asyncio.TaskGroup() as tg:
            for index, aw in enumerate(coros):
                tg.create_task(_one(index, aw))
        return cast("list[T]", results)


# ---- type_* -----------------------------------------------------------------


def type_is_mapping(value: object) -> TypeGuard[Mapping[str, object]]:
    """Return whether ``value`` is a mapping (narrows untrusted JSON-like input)."""
    return isinstance(value, Mapping)


def type_ensure_str(value: object) -> str:
    """Return ``value`` unchanged if it is a ``str``.

    Raises:
        TypeError: If ``value`` is not a ``str``.
    """
    if not isinstance(value, str):
        raise TypeError(f"expected str, got {type(value).__name__}")
    return value


# ---- hint_* -----------------------------------------------------------------


def hint_tag(*tags: str) -> HintRole:
    """Build annotation metadata carrying ``tags``."""
    return HintRole(name="tag", tags=tags)


# ---- vect_* -----------------------------------------------------------------


def vect_dot(a: Vec, b: Vec) -> float:
    """Return the dot product of two equal-length vectors.

    Raises:
        ValueError: If the lengths differ.
    """
    if len(a) != len(b):
        raise ValueError("vector length mismatch")
    return math.sumprod(a, b)


@wrappers.timed
def vect_l2(a: Vec, b: Vec) -> float:
    """Return the Euclidean distance between two equal-length vectors.

    Raises:
        ValueError: If the lengths differ.
    """
    if len(a) != len(b):
        raise ValueError("vector length mismatch")
    return math.dist(a, b)


# ---- math_* -----------------------------------------------------------------


def math_clamp(x: float, lo: float, hi: float) -> float:
    """Return ``x`` limited to ``[lo, hi]``.

    Raises:
        ValueError: If ``lo`` is greater than ``hi``.
    """
    if lo > hi:
        raise ValueError("lo must be <= hi")
    return max(lo, min(hi, x))


def math_safe_div(num: float, den: float, default: float = 0.0) -> float:
    """Return ``num / den``, or ``default`` when ``den`` is zero."""
    if den == 0.0:
        return default
    return num / den


# ---- db_* -------------------------------------------------------------------


def db_uri(path: str | Path, *, read_only: bool = False) -> str:
    """Return a SQLite URI for ``path`` (absolute, percent-encoded) for ``uri=True`` connects."""
    mode = "mode=ro" if read_only else "mode=rwc"
    return f"{Path(path).absolute().as_uri()}?{mode}"


# ---- batch_* ----------------------------------------------------------------


def batch_chunked[T](items: Sequence[T], size: int) -> list[Sequence[T]]:
    """Split ``items`` into consecutive chunks of at most ``size``.

    Raises:
        ValueError: If ``size`` is below 1.
    """
    if size < 1:
        raise ValueError("size must be >= 1")
    return [items[i : i + size] for i in range(0, len(items), size)]


# ---- cowork_* ---------------------------------------------------------------


def cowork_gil_enabled() -> bool:
    """Return whether the GIL is enabled, preferring the SDK probe when installed."""
    try:
        from swarm_sdk.execution.concurrency import gil_enabled as sdk_gil

        return sdk_gil()
    except ImportError:
        return CoworkRole.gil_enabled()


def cowork_parallel_cap() -> int:
    """Return the sibling-agent parallel cap, preferring the SDK value when installed."""
    try:
        from swarm_sdk.execution.concurrency import parallel_cap as sdk_cap

        return sdk_cap()
    except ImportError:
        return CoworkRole.parallel_cap()


__all__ = [
    "wrappers",
    "TypeRole",
    "HintRole",
    "VectRole",
    "DbRole",
    "BatchRole",
    "CoworkRole",
    "type_is_mapping",
    "type_ensure_str",
    "hint_tag",
    "vect_dot",
    "vect_l2",
    "math_clamp",
    "math_safe_div",
    "db_uri",
    "batch_chunked",
    "cowork_gil_enabled",
    "cowork_parallel_cap",
]


def main() -> int:
    """Smoke check for the eleven role functions (profile hot paths with ``SWARM_PROFILE=1``)."""
    checks = {
        "type_is_mapping": type_is_mapping({}) and not type_is_mapping([]),
        "type_ensure_str": type_ensure_str("a") == "a",
        "hint_tag": hint_tag("x").tags == ("x",),
        "vect_dot": vect_dot([1, 2], [3, 4]) == 11.0,
        "vect_l2": vect_l2([0, 0], [3, 4]) == 5.0,
        "math_clamp": math_clamp(5, 0, 1) == 1,
        "math_safe_div": math_safe_div(1, 0, default=-1.0) == -1.0,
        "db_uri": db_uri("/tmp/x.db", read_only=True).endswith("?mode=ro"),
        "batch_chunked": batch_chunked([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]],
        "cowork_gil_enabled": isinstance(cowork_gil_enabled(), bool),
        "cowork_parallel_cap": cowork_parallel_cap()
        in (GIL_PARALLEL_CAP, FREE_THREADED_PARALLEL_CAP),
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        logger.error("template smoke failed: %s", ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
