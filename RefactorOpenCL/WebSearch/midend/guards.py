"""Midend network guards: SSRF check for public-only fetches and bounded body reads."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    pass


class _ByteStream(Protocol):
    """The slice of an httpx response this module reads."""

    def read(self) -> bytes: ...

    def iter_bytes(self) -> Iterable[bytes]: ...


def _read_stream(response: _ByteStream, max_bytes: int | None) -> bytes:
    """Read an httpx stream, keeping at most ``max_bytes``."""
    if max_bytes is None:
        return response.read()
    chunks: list[bytes] = []
    remaining = max_bytes
    for chunk in response.iter_bytes():
        if remaining <= 0:
            break
        chunks.append(chunk[:remaining])
        remaining -= len(chunk)
    return b"".join(chunks)


_USER_AGENT = "Mozilla/5.0 (compatible; WebSearchBot/1.0)"


_MAX_REDIRECTS = 5


#: ``host -> addresses``. ``None`` uses the system resolver.
Resolver = Callable[[str], list[str]]


class PrivateTarget(Exception):
    """The URL, or a redirect hop, is not a public http(s) host.

    Not an ``OSError``: the fetch retry decorator treats ``OSError`` as transient,
    and a private target must not be requested again.
    """


def _require_public(url: str, resolver: Resolver | None) -> None:
    """Raise ``PrivateTarget`` unless ``url`` is public http(s)."""
    from WebSearch.browser_agent import is_public_http_url

    kwargs: dict[str, Resolver] = {} if resolver is None else {"resolver": resolver}
    if not is_public_http_url(url, **kwargs):
        raise PrivateTarget("non-public host refused")


def _guard_url(url: str, public_only: bool, resolver: Resolver | None) -> None:
    """Apply the httpx allowlist when ``public_only`` is set."""
    if public_only:
        _require_public(url, resolver)


def _capped(chunks: Iterable[bytes], max_bytes: int | None) -> bytes:
    """Join body chunks, keeping at most ``max_bytes`` (``None`` keeps all)."""
    if max_bytes is None:
        return b"".join(chunks)
    kept: list[bytes] = []
    remaining = max_bytes
    for chunk in chunks:
        if remaining <= 0:
            break
        kept.append(chunk[:remaining])
        remaining -= len(chunk)
    return b"".join(kept)
