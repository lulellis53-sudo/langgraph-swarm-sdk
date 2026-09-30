"""HTTP search APIs. Missing keys or import/network errors yield empty hits (fail closed)."""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from typing import Any

from WebSearch.frontend.providers import SearcherSpec
from WebSearch.frontend.websearchers import SearchHit
from WebSearch.repeater import repeater

#: Search implementation signature: ``(query, spec) -> hits``.
SearchFn = Callable[[str, SearcherSpec], Sequence[SearchHit]]


def _key(spec: SearcherSpec) -> str:
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


def _base(spec: SearcherSpec) -> str:
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
def _httpx_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    params: dict[str, str] | None = None,
) -> Any:
    """GET/POST JSON. Deferred httpx import.

    Args:
        method (str): ``GET`` or ``POST``.
        url (str): Absolute URL.
        headers (dict[str, str] | None): Extra headers.
        json_body (dict[str, Any] | None): POST body.
        params (dict[str, str] | None): Query string.

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
            timeout=20.0,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise OSError(str(exc)) from exc


def search_brave(query: str, spec: SearcherSpec) -> list[SearchHit]:
    """Brave Search API.

    Args:
        query (str): User query.
        spec (SearcherSpec): Needs ``BRAVE_API_KEY`` via ``api_key_env``.

    Returns:
        list[SearchHit]: Web results, or ``[]`` if the key is missing or the call fails.
    """
    token = _key(spec)
    if not token:
        return []
    try:
        data = _httpx_json(
            "GET",
            "https://api.search.brave.com/res/v1/web/search",
            headers={"Accept": "application/json", "X-Subscription-Token": token},
            params={"q": query},
        )
    except (TimeoutError, OSError, ConnectionError, ValueError):
        return []
    web = data.get("web") if isinstance(data, dict) else None
    results = web.get("results") if isinstance(web, dict) else None
    return _hits_from_maps(results, spec.id, title="title", url="url", snippet="description")


def search_tavily(query: str, spec: SearcherSpec) -> list[SearchHit]:
    """Tavily Search API.

    Args:
        query (str): User query.
        spec (SearcherSpec): Needs ``TAVILY_API_KEY``.

    Returns:
        list[SearchHit]: Results, or ``[]`` on missing key / failure.
    """
    token = _key(spec)
    if not token:
        return []
    try:
        data = _httpx_json(
            "POST",
            "https://api.tavily.com/search",
            json_body={"api_key": token, "query": query, "max_results": 8},
        )
    except (TimeoutError, OSError, ConnectionError, ValueError):
        return []
    results = data.get("results") if isinstance(data, dict) else None
    return _hits_from_maps(results, spec.id, title="title", url="url", snippet="content")


def search_apify(query: str, spec: SearcherSpec) -> list[SearchHit]:
    """Apify API probe. Fails closed without ``APIFY_TOKEN`` or on HTTP errors.

    Args:
        query (str): Unused except as a future actor input.
        spec (SearcherSpec): ``base_url`` plus ``APIFY_TOKEN``.

    Returns:
        list[SearchHit]: Actor list rows if the token works; otherwise ``[]``.
    """
    del query
    token = _key(spec)
    if not token:
        return []
    root = _base(spec) or "https://api.apify.com/v2"
    try:
        data = _httpx_json(
            "GET",
            f"{root}/acts",
            headers={"Authorization": f"Bearer {token}"},
            params={"limit": "1"},
        )
    except (TimeoutError, OSError, ConnectionError, ValueError):
        return []
    bucket = data.get("data") if isinstance(data, dict) else None
    items = bucket.get("items") if isinstance(bucket, dict) else None
    if not isinstance(items, list):
        return []
    hits: list[SearchHit] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("id") or "")
        if not name:
            continue
        hits.append(
            SearchHit(title=name, url=f"{root}/acts/{name}", snippet="", searcher_id=spec.id)
        )
    return hits


def search_exa(query: str, spec: SearcherSpec) -> list[SearchHit]:
    """Exa Search API.

    Args:
        query (str): User query.
        spec (SearcherSpec): Needs ``EXA_API_KEY``.

    Returns:
        list[SearchHit]: Results, or ``[]`` on missing key / failure.
    """
    token = _key(spec)
    if not token:
        return []
    try:
        data = _httpx_json(
            "POST",
            "https://api.exa.ai/search",
            headers={"x-api-key": token, "Content-Type": "application/json"},
            json_body={"query": query, "numResults": 8},
        )
    except (TimeoutError, OSError, ConnectionError, ValueError):
        return []
    results = data.get("results") if isinstance(data, dict) else None
    return _hits_from_maps(results, spec.id, title="title", url="url", snippet="text")


def search_searxng(query: str, spec: SearcherSpec) -> list[SearchHit]:
    """SearXNG JSON search with DuckDuckGo + Bing engines.

    Args:
        query (str): User query.
        spec (SearcherSpec): ``base_url_env`` (``SEARXNG_URL``) and ``engine``.

    Returns:
        list[SearchHit]: Results, or ``[]`` if the instance URL is unset or the call fails.
    """
    root = _base(spec)
    if not root:
        return []
    engines = spec.engine or "duckduckgo,bing"
    try:
        data = _httpx_json(
            "GET",
            f"{root}/search",
            params={"q": query, "format": "json", "engines": engines},
        )
    except (TimeoutError, OSError, ConnectionError, ValueError):
        return []
    results = data.get("results") if isinstance(data, dict) else None
    return _hits_from_maps(results, spec.id, title="title", url="url", snippet="content")


def _hits_from_maps(
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


def builtin_searchers() -> dict[str, SearchFn]:
    """Named HTTP searchers from ``providers.yaml`` ids.

    Returns:
        dict[str, SearchFn]: brave, tavily, apify, exa, searxng.
    """
    return {
        "brave": search_brave,
        "tavily": search_tavily,
        "apify": search_apify,
        "exa": search_exa,
        "searxng": search_searxng,
    }


__all__ = [
    "builtin_searchers",
    "search_apify",
    "search_brave",
    "search_exa",
    "search_searxng",
    "search_tavily",
]
