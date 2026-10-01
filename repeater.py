"""Shared retry and URL canonicalization helpers.

Use ``@repeater.s`` or ``@repeater.s(times=3)`` on functions that may raise
transient network errors. The decorator catches ``TimeoutError``, ``OSError``,
and ``ConnectionError`` by default and re-runs the wrapped function up to
``times`` attempts before surfacing the last exception.

Use :func:`normalize_url` to produce stable URL keys for deduplication.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import ParamSpec, TypeVar, overload
from urllib.parse import parse_qsl, urlencode, urlsplit

P = ParamSpec("P")
R = TypeVar("R")

#: Exceptions that are assumed to be transient and therefore retriable.
_TRANSIENT: tuple[type[BaseException], ...] = (TimeoutError, OSError, ConnectionError)

#: Query params that never change the target page; dropped when deduplicating URLs.
_TRACKING_PARAMS = frozenset({"fbclid", "gclid", "msclkid", "ref", "ref_src"})


def normalize_url(url: str) -> str:
    """Return a canonical key for *url* so duplicates collapse.

    Lowercases scheme and host, drops ``www.``, fragments, trailing slashes,
    default ports and tracking params (``utm_*``, ``gclid``, ...), and sorts
    the remaining query params.

    Args:
        url (str): Absolute URL.

    Returns:
        str: Canonical form, used for comparison only.
    """
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").removeprefix("www.")
    default_port = {"http": 80, "https": 443}.get(parts.scheme.lower())
    if parts.port is not None and parts.port != default_port:
        host = f"{host}:{parts.port}"
    query = sorted(
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in _TRACKING_PARAMS
    )
    path = parts.path.rstrip("/")
    return f"{parts.scheme.lower()}://{host}{path}" + (f"?{urlencode(query)}" if query else "")


class _Repeater:
    """Namespace for the retry decorator factory.

    The public singleton :data:`repeater` exposes :meth:`s`, which supports
    both bare ``@repeater.s`` and parameterized ``@repeater.s(times=3)``
    usage. Keeping the implementation in a small private class makes the
    overload signatures self-contained and avoids polluting the module scope.
    """

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
        """Retry *times* on transient errors.

        The default retry set is ``TimeoutError``, ``OSError``, and
        ``ConnectionError``. Logic bugs and unexpected exceptions are never
        retried.

        Args:
            fn: Decorated function when used as ``@repeater.s``.
            times: Total attempts, including the first try. Values below 1
                are clamped to 1.
            on: Exception classes that trigger a retry.

        Returns:
            The wrapped function when ``fn`` is supplied; otherwise a
            decorator that accepts the function.
        """

        def decorate(func: Callable[P, R]) -> Callable[P, R]:
            @functools.wraps(func)
            def inner(*args: P.args, **kwargs: P.kwargs) -> R:
                last: BaseException | None = None
                # Attempt up to ``times`` times, remembering the last retriable
                # exception so we can re-raise it if all attempts fail.
                for _ in range(max(times, 1)):
                    try:
                        return func(*args, **kwargs)
                    except on as exc:
                        last = exc
                # If every attempt raised a retriable exception, surface the
                # last one so callers see the actual failure.
                if last is not None:
                    raise last
                # ``times`` was clamped to 1 and the loop body somehow did not
                # return; this path is unreachable but keeps the type checker
                # happy because ``R`` must be returned.
                return func(*args, **kwargs)

            return inner

        if fn is not None:
            return decorate(fn)
        return decorate


#: Public retry decorator factory. Import as ``from WebSearch.repeater import repeater``.
repeater = _Repeater()

__all__ = ["normalize_url", "repeater"]
