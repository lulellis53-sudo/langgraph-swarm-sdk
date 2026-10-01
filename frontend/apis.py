"""HTTP search APIs. Missing keys or import/network errors yield empty hits (fail closed)."""

from __future__ import annotations

from dataclasses import replace

from WebSearch.frontend.http import call_json as _httpx_json
from WebSearch.frontend.http import dig, env_base, env_key, hits_from_maps
from WebSearch.frontend.models import SearchFn, SearchHit
from WebSearch.frontend.providers import SearcherSpec

_APIFY_ACTOR = "apify~google-search-scraper"


def search_brave(query: str, spec: SearcherSpec) -> list[SearchHit]:
    """Brave Search API.

    Args:
        query (str): User query.
        spec (SearcherSpec): Needs ``BRAVE_API_KEY`` via ``api_key_env``.

    Returns:
        list[SearchHit]: Web results, or ``[]`` if the key is missing or the call fails.
    """
    token = env_key(spec)
    if not token:
        return []
    data = _httpx_json(
        "GET",
        "https://api.search.brave.com/res/v1/web/search",
        headers={"Accept": "application/json", "X-Subscription-Token": token},
        params={"q": query},
    )
    if data is None:
        return []
    return hits_from_maps(
        dig(data, "web", "results"), spec.id, title="title", url="url", snippet="description"
    )


def search_tavily(query: str, spec: SearcherSpec) -> list[SearchHit]:
    """Tavily Search API.

    Args:
        query (str): User query.
        spec (SearcherSpec): Needs ``TAVILY_API_KEY``.

    Returns:
        list[SearchHit]: Results, or ``[]`` on missing key / failure.
    """
    token = env_key(spec)
    if not token:
        return []
    data = _httpx_json(
        "POST",
        "https://api.tavily.com/search",
        json_body={"api_key": token, "query": query, "max_results": 8},
    )
    if data is None:
        return []
    return hits_from_maps(
        dig(data, "results"), spec.id, title="title", url="url", snippet="content"
    )


def search_apify(query: str, spec: SearcherSpec) -> list[SearchHit]:
    """Google SERP through the Apify ``google-search-scraper`` actor (sync run).

    Args:
        query (str): User query (dork strings work as-is).
        spec (SearcherSpec): ``base_url`` plus ``APIFY_TOKEN``.

    Returns:
        list[SearchHit]: Organic results, or ``[]`` without a token or on failure.
    """
    token = env_key(spec)
    if not token:
        return []
    root = env_base(spec) or "https://api.apify.com/v2"
    data = _httpx_json(
        "POST",
        f"{root}/acts/{_APIFY_ACTOR}/run-sync-get-dataset-items",
        headers={"Authorization": f"Bearer {token}"},
        json_body={"queries": query, "maxPagesPerQuery": 1, "resultsPerPage": 10},
        timeout_s=120.0,
    )
    if not isinstance(data, list):
        return []
    hits: list[SearchHit] = []
    for page in data:
        organic = dig(page, "organicResults")
        hits.extend(
            hits_from_maps(organic, spec.id, title="title", url="url", snippet="description")
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
    token = env_key(spec)
    if not token:
        return []
    data = _httpx_json(
        "POST",
        "https://api.exa.ai/search",
        headers={"x-api-key": token, "Content-Type": "application/json"},
        json_body={"query": query, "numResults": 8},
    )
    if data is None:
        return []
    return hits_from_maps(dig(data, "results"), spec.id, title="title", url="url", snippet="text")


def search_searxng(query: str, spec: SearcherSpec) -> list[SearchHit]:
    """SearXNG JSON search with DuckDuckGo + Bing engines.

    Args:
        query (str): User query.
        spec (SearcherSpec): ``base_url_env`` (``SEARXNG_URL``) and ``engine``.

    Returns:
        list[SearchHit]: Results, or ``[]`` if the instance URL is unset or the call fails.
    """
    root = env_base(spec)
    if not root:
        return []
    engines = spec.engine or "duckduckgo,bing"
    data = _httpx_json(
        "GET",
        f"{root}/search",
        params={"q": query, "format": "json", "engines": engines},
    )
    if data is None:
        return []
    return hits_from_maps(
        dig(data, "results"), spec.id, title="title", url="url", snippet="content"
    )


def search_google_ground(query: str, spec: SearcherSpec) -> list[SearchHit]:
    """Gemini with Google Search grounding; returns the cited web sources.

    ``spec.engine`` is the model id, ``spec.base_url`` the API root, and the key
    comes from ``GEMINI_API_KEY``. Cited URIs are Google redirect links; the
    midend follows redirects when scraping.

    Args:
        query (str): User query (dork strings work as-is).
        spec (SearcherSpec): Searcher configuration.

    Returns:
        list[SearchHit]: One hit per grounding chunk. The API-reported token total
        is stored on the first hit. ``[]`` without a key or on failure.
    """
    token = env_key(spec)
    if not token:
        return []
    root = env_base(spec) or "https://generativelanguage.googleapis.com/v1beta"
    model = spec.engine or "gemini-2.5-flash"
    data = _httpx_json(
        "POST",
        f"{root}/models/{model}:generateContent",
        headers={"x-goog-api-key": token, "Content-Type": "application/json"},
        json_body={
            "contents": [{"parts": [{"text": query}]}],
            "tools": [{"google_search": {}}],
        },
        timeout_s=60.0,
    )
    candidates = dig(data, "candidates")
    if not isinstance(candidates, list) or not candidates:
        return []
    meta = dig(candidates[0], "groundingMetadata")
    chunks = dig(meta, "groundingChunks")
    if not isinstance(chunks, list):
        return []
    quoted: dict[int, list[str]] = {}
    supports = dig(meta, "groundingSupports")
    for support in supports if isinstance(supports, list) else []:
        text = dig(support, "segment", "text")
        idxs = dig(support, "groundingChunkIndices")
        if isinstance(text, str) and isinstance(idxs, list):
            for i in idxs:
                if isinstance(i, int):
                    quoted.setdefault(i, []).append(text)
    rows = [
        {**web, "snippet": " ".join(quoted.get(i, []))}
        for i, chunk in enumerate(chunks)
        if isinstance(web := dig(chunk, "web"), dict)
    ]
    hits = hits_from_maps(rows, spec.id, title="title", url="uri", snippet="snippet")
    total = dig(data, "usageMetadata", "totalTokenCount")
    if hits and isinstance(total, int):
        hits[0] = replace(hits[0], api_tokens=total)
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
        "google_ground": search_google_ground,
        "searxng": search_searxng,
    }


__all__ = [
    "builtin_searchers",
    "search_apify",
    "search_brave",
    "search_exa",
    "search_google_ground",
    "search_searxng",
    "search_tavily",
]
