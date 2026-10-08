"""Shared HTTP client, executor, and JSON request utilities."""

from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from WebSearch.repeater import repeater

if TYPE_CHECKING:
    from httpx import Client as HttpxClient

logger = logging.getLogger(__name__)

_MAX_WORKERS = 8

_HTTP_CLIENT: HttpxClient | None = None
_HTTP_CLIENT_LOCK = threading.Lock()
_EXECUTOR: ThreadPoolExecutor | None = None
_EXECUTOR_LOCK = threading.Lock()


def shared_http_client() -> HttpxClient:
    """Process-wide ``httpx.Client`` so TCP/TLS connections are reused."""
    global _HTTP_CLIENT
    if _HTTP_CLIENT is None:
        with _HTTP_CLIENT_LOCK:
            if _HTTP_CLIENT is None:
                import httpx

                try:
                    _HTTP_CLIENT = httpx.Client(http2=True)
                except ImportError:
                    # h2 optional: HTTP/2 multiplexing when present, else HTTP/1.1.
                    _HTTP_CLIENT = httpx.Client()
    return _HTTP_CLIENT


def shared_executor() -> ThreadPoolExecutor:
    """Process-wide worker pool; callers must never shut it down."""
    global _EXECUTOR
    if _EXECUTOR is None:
        with _EXECUTOR_LOCK:
            if _EXECUTOR is None:
                _EXECUTOR = ThreadPoolExecutor(
                    max_workers=_MAX_WORKERS, thread_name_prefix="websearch"
                )
    return _EXECUTOR


def _json_loads(data: bytes | str) -> Any:
    """Parse JSON via orjson (orjson.JSONDecodeError subclasses json's)."""
    try:
        import orjson

        return orjson.loads(data)
    except ImportError:
        return json.loads(data)


@repeater.s
def request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    params: dict[str, str] | None = None,
    timeout_s: float = 20.0,
) -> Any:
    """GET/POST JSON. Deferred httpx import.

    Raises:
        TimeoutError, OSError, ConnectionError: After retries.
    """
    try:
        import httpx
    except ImportError as exc:
        raise OSError("httpx not installed") from exc

    try:
        response = shared_http_client().request(
            method,
            url,
            headers=headers,
            json=json_body,
            params=params,
            timeout=timeout_s,
        )
        response.raise_for_status()
        return _json_loads(response.content)
    except httpx.HTTPError as exc:
        raise OSError(str(exc)) from exc


def call_json(method: str, url: str, **kwargs: Any) -> Any | None:
    """Fail-closed wrapper over :func:`request_json`.

    Returns ``None`` on a transient network failure or a body that is not valid JSON.
    Other errors propagate.
    """
    try:
        return request_json(method, url, **kwargs)
    except (
        TimeoutError,
        OSError,
        ConnectionError,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ) as exc:
        # Host and status only: httpx messages embed the full URL, which may carry a key.
        logger.warning(
            "%s %s failed: %s %s",
            method,
            urlsplit(url).netloc,
            type(exc).__name__,
            str(exc).split(" for url", 1)[0][:120],
        )
        return None


def dig(data: Any, *path: str) -> object:
    """Walk nested dicts along *path*; ``None`` if any step is not a dict."""
    node: object = data
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node
