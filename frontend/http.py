"""Shared HTTP/JSON plumbing for the search APIs (fail closed on errors)."""

from __future__ import annotations

import os
from typing import Any

from WebSearch.frontend.models import SearchHit
from WebSearch.frontend.providers import SearcherSpec
from WebSearch.repeater import repeater


def env_key(spec: SearcherSpec) -> str:
    """Read an API key from the environment using the spec's env var name.

    Args:
        spec: Searcher configuration from ``providers.yaml``.

    Returns:
        str: The trimmed key, or an empty string if the env var is unset.
    """
    name = spec.api_key_env
    if not name:
        return ""
    return os.environ.get(name, "").strip()


def env_base(spec: SearcherSpec) -> str:
    """Resolve the searcher base URL from env var or spec field.

    Args:
        spec: Searcher configuration from ``providers.yaml``.

    Returns:
        str: Root URL with trailing slashes removed, or an empty string.
    """
    if spec.base_url_env:
        return os.environ.get(spec.base_url_env, "").strip().rstrip("/")
    return (spec.base_url or "").rstrip("/")


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

    Args:
        method (str): ``GET`` or ``POST``.
        url (str): Absolute URL.
        headers (dict[str, str] | None): Extra headers.
        json_body (dict[str, Any] | None): POST body.
        params (dict[str, str] | None): Query string.
        timeout_s (float): Request timeout in seconds.

    Returns:
        Any: Parsed JSON.

    Raises:
        TimeoutError, OSError, ConnectionError: After retries.
    """
    try:
        import httpx
    except ImportError as exc:
        raise OSError("httpx not installed") from exc

    try:
        response = httpx.request(
            method,
            url,
            headers=headers,
            json=json_body,
            params=params,
            timeout=timeout_s,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise OSError(str(exc)) from exc


def call_json(method: str, url: str, **kwargs: Any) -> Any | None:
    """Fail-closed wrapper over :func:`request_json`.

    Returns:
        Any | None: Parsed JSON, or ``None`` on any transient/parse failure.
    """
    try:
        return request_json(method, url, **kwargs)
    except TimeoutError, OSError, ConnectionError, ValueError:
        return None


def dig(data: Any, *path: str) -> object:
    """Walk nested dicts along *path*; ``None`` if any step is not a dict."""
    node: object = data
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def hits_from_maps(
    rows: object,
    searcher_id: str,
    *,
    title: str,
    url: str,
    snippet: str,
) -> list[SearchHit]:
    """Normalize a list of raw result dicts into ``SearchHit`` objects.

    Rows without an ``http``/``https`` URL are skipped so downstream callers
    never have to validate schemes themselves.

    Args:
        rows: Raw result list from a search API response.
        searcher_id: Identifier of the searcher that produced the rows.
        title: Key in each row dict that holds the result title.
        url: Key in each row dict that holds the result URL.
        snippet: Key in each row dict that holds the result snippet.

    Returns:
        list[SearchHit]: Valid, normalized hits.
    """
    if not isinstance(rows, list):
        return []
    hits: list[SearchHit] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        href = str(row.get(url) or "")
        if not href.startswith("http"):
            continue
        hits.append(
            SearchHit(
                title=str(row.get(title) or href),
                url=href,
                snippet=str(row.get(snippet) or ""),
                searcher_id=searcher_id,
            )
        )
    return hits


__all__ = ["call_json", "dig", "env_base", "env_key", "hits_from_maps", "request_json"]
