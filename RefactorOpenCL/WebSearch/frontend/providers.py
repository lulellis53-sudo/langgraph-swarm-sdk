"""HTTP search API implementations for every configured provider."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import replace
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode, urlsplit

from WebSearch.frontend.http_utils import call_json, dig, request_json, shared_http_client
from WebSearch.frontend.secrets import env_base, env_key, env_keys
from WebSearch.frontend.types import SearcherSpec

if TYPE_CHECKING:
    from mcp import StdioServerParameters

logger = logging.getLogger(__name__)

_APIFY_ACTOR = "apify~google-search-scraper"
_ROTATE_STATUSES = frozenset({401, 403, 429})
_STATUS = re.compile(r"\b([1-5]\d\d)\b")


def hits_from_maps(
    rows: object,
    searcher_id: str,
    *,
    title: str,
    url: str,
    snippet: str,
) -> list:
    """Normalize a list of raw result dicts into ``SearchHit`` objects.

    Rows without an ``http``/``https`` URL are skipped so downstream callers
    never have to validate schemes themselves.
    """
    from WebSearch.frontend.types import SearchHit

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


def _http_status(exc: BaseException) -> int | None:
    """HTTP status in an ``OSError`` raised by :func:`request_json`, else ``None``."""
    head = str(exc).split(" for url", 1)[0]
    match = _STATUS.search(head)
    return int(match.group(1)) if match else None


# --- provider implementations ---------------------------------------------------


async def _bright_data_search(query: str, token: str, engine: str) -> object:
    """Call the hosted Bright Data MCP search tool using its in-memory token URL."""
    from mcp import Client

    url = "https://mcp.brightdata.com/mcp?" + urlencode({"token": token})
    async with Client(url) as client:
        result = await client.call_tool("search_engine", {"query": query, "engine": engine})
    if result.is_error:
        return None
    if result.structured_content is not None:
        return result.structured_content
    for block in result.content:
        value = getattr(block, "text", None)
        if isinstance(value, str):
            try:
                return json.loads(_unwrap_untrusted(value))
            except json.JSONDecodeError:
                continue
    return None


def _unwrap_untrusted(text: str) -> str:
    """Return the body between Bright Data's ``UNTRUSTED_<id>_BEGIN/END`` markers.

    Only the marker pair carrying the exact id announced in the notice counts, so
    page text cannot forge a closing marker. Unwrapped text passes through unchanged.
    """
    announced = re.search(r"exact id \(([0-9a-f]+)\)", text)
    if not announced:
        return text
    marker = announced.group(1)
    body = re.search(
        rf"=====UNTRUSTED_{marker}_BEGIN=====\n(.*)\n=====UNTRUSTED_{marker}_END=====",
        text,
        re.DOTALL,
    )
    return body.group(1) if body else text


def _bright_data_hits(payload: object, searcher_id: str) -> list:
    """Normalize Bright Data's Google JSON results into WebSearch hits."""
    if isinstance(payload, dict):
        for field in ("organic", "results", "organicResults", "data", "result"):
            if field in payload:
                return _bright_data_hits(payload[field], searcher_id)
    if not isinstance(payload, list):
        return []
    return hits_from_maps(
        [
            {
                "title": r.get("title"),
                "url": r.get("link") or r.get("url"),
                "snippet": r.get("description") or r.get("snippet") or "",
            }
            for r in payload
            if isinstance(r, dict)
        ],
        searcher_id,
        title="title",
        url="url",
        snippet="snippet",
    )


def search_bright_data(query: str, spec: SearcherSpec) -> list:
    """Search Bright Data's hosted MCP without storing its token in configuration."""
    token = env_key(spec)
    if not token:
        return []
    try:
        payload = asyncio.run(_bright_data_search(query, token, spec.engine or "google"))
    except Exception:  # noqa: BLE001 - provider boundary must not expose token-bearing URLs
        return []
    return _bright_data_hits(payload, spec.id)


def search_brave(query: str, spec: SearcherSpec) -> list:
    """Brave Search API."""
    token = env_key(spec)
    if not token:
        return []
    data = call_json(
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


def search_tavily(query: str, spec: SearcherSpec) -> list:
    """Tavily Search API."""
    token = env_key(spec)
    if not token:
        return []
    body: dict[str, Any] = {"api_key": token, "query": query, "max_results": 8}
    if spec.dork == "translate":
        from WebSearch.frontend.dorks import parse_dork

        parsed = parse_dork(query)
        if parsed.plain():
            body["query"] = parsed.plain()
        if parsed.sites:
            body["include_domains"] = list(parsed.sites)
        if parsed.exclude_sites:
            body["exclude_domains"] = list(parsed.exclude_sites)
        if parsed.after:
            body["start_date"] = parsed.after
        if parsed.before:
            body["end_date"] = parsed.before
    data = call_json("POST", "https://api.tavily.com/search", json_body=body)
    if data is None:
        return []
    return hits_from_maps(
        dig(data, "results"), spec.id, title="title", url="url", snippet="content"
    )


def search_parallel(query: str, spec: SearcherSpec) -> list:
    """Parallel Search API."""
    token = env_key(spec)
    if not token:
        return []

    body: dict[str, Any] = {
        "objective": query,
        "search_queries": [query],
        "mode": spec.engine if spec.engine in {"turbo", "fast", "basic", "advanced"} else "fast",
        "advanced_settings": {"max_results": 8},
    }
    advanced: dict[str, Any] = body["advanced_settings"]
    if spec.dork == "translate":
        from WebSearch.frontend.dorks import parse_dork

        parsed = parse_dork(query)
        if parsed.plain():
            body["objective"] = parsed.plain()
            body["search_queries"] = [parsed.plain()]
        source_policy: dict[str, Any] = {}
        if parsed.sites:
            source_policy["include_domains"] = list(parsed.sites)
        if parsed.exclude_sites:
            source_policy["exclude_domains"] = list(parsed.exclude_sites)
        if parsed.after:
            source_policy["after_date"] = parsed.after
        if source_policy:
            advanced["source_policy"] = source_policy

    data = call_json(
        "POST",
        "https://api.parallel.ai/v1/search",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-api-key": token,
        },
        json_body=body,
    )
    rows = dig(data, "results")
    if not isinstance(rows, list):
        return []
    normalized: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        excerpts = row.get("excerpts")
        snippet = (
            " ".join(str(item) for item in excerpts if item) if isinstance(excerpts, list) else ""
        )
        normalized.append(
            {
                "title": str(row.get("title") or ""),
                "url": str(row.get("url") or ""),
                "snippet": snippet,
            }
        )
    return hits_from_maps(normalized, spec.id, title="title", url="url", snippet="snippet")


def search_jina(query: str, spec: SearcherSpec) -> list:
    """Jina Search Foundation API."""
    token = env_key(spec)
    if not token:
        return []
    root = env_base(spec) or "https://s.jina.ai"
    data = call_json(
        "POST",
        f"{root}/",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json_body={"q": query, "num": 8},
    )
    rows = dig(data, "data")
    if not isinstance(rows, list):
        return []
    prepared: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        if not item.get("description") and isinstance(item.get("content"), str):
            item["description"] = item["content"][:280]
        prepared.append(item)
    hits = hits_from_maps(prepared, spec.id, title="title", url="url", snippet="description")
    usage = dig(prepared[0], "usage", "tokens") if prepared else None
    if hits and isinstance(usage, int):
        hits[0] = replace(hits[0], api_tokens=usage)
    return hits


def search_apify(query: str, spec: SearcherSpec) -> list:
    """Google SERP through the Apify ``google-search-scraper`` actor (sync run)."""
    token = env_key(spec)
    if not token:
        return []
    root = env_base(spec) or "https://api.apify.com/v2"
    data = call_json(
        "POST",
        f"{root}/acts/{_APIFY_ACTOR}/run-sync-get-dataset-items",
        headers={"Authorization": f"Bearer {token}"},
        json_body={"queries": query, "maxPagesPerQuery": 1, "resultsPerPage": 10},
        timeout_s=120.0,
    )
    if not isinstance(data, list):
        return []
    hits = []
    for page in data:
        organic = dig(page, "organicResults")
        hits.extend(
            hits_from_maps(organic, spec.id, title="title", url="url", snippet="description")
        )
    return hits


def search_exa(query: str, spec: SearcherSpec) -> list:
    """Exa Search API."""
    token = env_key(spec)
    if not token:
        return []
    body: dict[str, Any] = {"query": query, "numResults": 8}
    body["contents"] = {"text": {"maxCharacters": 300}}
    if spec.dork == "translate":
        from WebSearch.frontend.dorks import parse_dork

        parsed = parse_dork(query)
        if parsed.plain():
            body["query"] = parsed.plain()
        if parsed.sites:
            body["includeDomains"] = list(parsed.sites)
        if parsed.exclude_sites:
            body["excludeDomains"] = list(parsed.exclude_sites)
        if parsed.after:
            body["startPublishedDate"] = parsed.after
        if parsed.before:
            body["endPublishedDate"] = parsed.before
    data = call_json(
        "POST",
        "https://api.exa.ai/search",
        headers={"x-api-key": token, "Content-Type": "application/json"},
        json_body=body,
    )
    if data is None:
        return []
    return hits_from_maps(dig(data, "results"), spec.id, title="title", url="url", snippet="text")


def search_openrouter_web(query: str, spec: SearcherSpec) -> list:
    """OpenRouter web-search plugin: a cheap model runs a web search and cites sources."""
    keys = env_keys(spec)
    if not keys:
        return []
    plugin: dict[str, Any] = {"id": "web", "max_results": 8}
    text = query
    if spec.dork == "translate":
        from WebSearch.frontend.dorks import parse_dork

        parsed = parse_dork(query)
        text = parsed.plain() or query
        if parsed.sites:
            plugin["include_domains"] = list(parsed.sites)
        if parsed.exclude_sites:
            plugin["exclude_domains"] = list(parsed.exclude_sites)
    data = call_json(
        "POST",
        f"{env_base(spec) or 'https://openrouter.ai/api/v1'}/chat/completions",
        headers={"Authorization": f"Bearer {keys[0]}", "Content-Type": "application/json"},
        json_body={
            "model": spec.engine or "openai/gpt-oss-20b:free",
            "messages": [
                {
                    "role": "user",
                    "content": f"Search the web for: {text}\nReply with one short sentence.",
                }
            ],
            "plugins": [plugin],
            "max_tokens": 64,
        },
        timeout_s=60.0,
    )
    annotations = dig(data, "choices")
    message = (
        dig(annotations[0], "message") if isinstance(annotations, list) and annotations else None
    )
    notes = dig(message, "annotations")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for note in notes if isinstance(notes, list) else []:
        if not isinstance(note, dict) or note.get("type") != "url_citation":
            continue
        cite = note.get("url_citation")
        info = cite if isinstance(cite, dict) else note
        url = info.get("url")
        if isinstance(url, str) and url not in seen:
            seen.add(url)
            rows.append(
                {
                    "url": url,
                    "title": info.get("title") or url,
                    "snippet": info.get("content") or "",
                }
            )
    hits = hits_from_maps(rows, spec.id, title="title", url="url", snippet="snippet")
    total = dig(data, "usage", "total_tokens")
    if hits and isinstance(total, int):
        hits[0] = replace(hits[0], api_tokens=total)
    return hits


def search_google_search(query: str, spec: SearcherSpec) -> list:
    """Gemini with Google Search grounding; returns the cited web sources."""
    keys = env_keys(spec)
    if not keys:
        return []
    root = env_base(spec) or "https://generativelanguage.googleapis.com/v1beta"
    model = spec.engine or "gemini-3.5-flash"
    body = {"contents": [{"parts": [{"text": query}]}], "tools": [{"google_search": {}}]}
    data: Any = None
    for index, token in enumerate(keys, start=1):
        try:
            data = request_json(
                "POST",
                f"{root}/models/{model}:generateContent",
                headers={"x-goog-api-key": token, "Content-Type": "application/json"},
                json_body=body,
                timeout_s=60.0,
            )
            break
        except (TimeoutError, OSError, ConnectionError, ValueError) as exc:
            status = _http_status(exc)
            logger.warning(
                "google_search key %d/%d failed: %s %s",
                index,
                len(keys),
                type(exc).__name__,
                status or "",
            )
            if status not in _ROTATE_STATUSES:
                return []
    if data is None:
        return []
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
    queries = dig(meta, "webSearchQueries")
    logger.info(
        "google_search: %s search queries run by %s (Gemini 3 bills per query)",
        len(queries) if isinstance(queries, list) else 0,
        model,
    )
    total = dig(data, "usageMetadata", "totalTokenCount")
    if hits and isinstance(total, int):
        hits[0] = replace(hits[0], api_tokens=total)
    return hits


def search_kimi(query: str, spec: SearcherSpec) -> list:
    """Moonshot Kimi Web Search Basic API."""
    token = env_key(spec)
    if not token:
        return []
    body: dict[str, Any] = {"text_query": query, "limit": 8, "timeout_seconds": 30}
    if spec.dork == "translate":
        from WebSearch.frontend.dorks import parse_dork

        parsed = parse_dork(query)
        if parsed.plain():
            body["text_query"] = parsed.plain()
        if parsed.sites:
            body["sites"] = list(parsed.sites)[:5]
        if parsed.after or parsed.before:
            body["time_window"] = {}
            if parsed.after:
                body["time_window"]["start"] = parsed.after
            if parsed.before:
                body["time_window"]["end"] = parsed.before
    root = env_base(spec) or "https://api.moonshot.ai"
    data = call_json(
        "POST",
        f"{root}/v1/tools/search",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json_body=body,
        timeout_s=60.0,
    )
    if data is None:
        return []
    return hits_from_maps(
        dig(data, "search_results"), spec.id, title="title", url="url", snippet="snippet"
    )


def search_ddg(query: str, spec: SearcherSpec) -> list:
    """DuckDuckGo text search via ``ddgs``."""
    from WebSearch.frontend.types import SearchHit

    del spec
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS  # ty: ignore[unresolved-import]
        except ImportError as exc:
            raise OSError("ddgs not installed (uv sync --extra websearch)") from exc

    try:
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=10)
    except Exception as exc:
        logger.warning("ddg search failed: %s", type(exc).__name__)
        return []
    return [
        SearchHit(
            title=str(item.get("title") or item.get("href") or ""),
            url=str(item["href"]),
            snippet=str(item.get("body") or ""),
            searcher_id="ddg",
        )
        for item in results
        if isinstance(item, dict) and str(item.get("href", "")).startswith("http")
    ]


def search_ddg_lite(query: str, spec: SearcherSpec) -> list:
    """DuckDuckGo Lite: scrape the plain-HTML endpoint, no API key or package."""
    from WebSearch.frontend.types import SearchHit

    try:
        from selectolax.lexbor import LexborHTMLParser as HTMLParser
    except ImportError as exc:
        raise OSError("selectolax not installed (uv sync --extra websearch)") from exc

    client = shared_http_client()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        ),
        "Referer": "https://lite.duckduckgo.com/",
    }
    try:
        response = client.get(
            "https://lite.duckduckgo.com/lite/", params={"q": query}, headers=headers
        )
        response.raise_for_status()
    except Exception as exc:
        logger.warning("ddg-lite failed: %s", type(exc).__name__)
        return []
    tree = HTMLParser(response.text)
    links = tree.css("a.result-link")
    snippets = tree.css("td.result-snippet")
    hits: list[SearchHit] = []
    for index, link in enumerate(links):
        url = _unwrap_lite_href(str(link.attributes.get("href") or ""))
        if not url:
            continue
        hits.append(
            SearchHit(
                title=link.text(strip=True) or url,
                url=url,
                snippet=snippets[index].text(strip=True) if index < len(snippets) else "",
                searcher_id=spec.id,
            )
        )
    return hits


def _unwrap_lite_href(href: str) -> str:
    """Resolve a DuckDuckGo Lite redirect href to its target URL."""
    from urllib.parse import parse_qs

    if href.startswith("//"):
        href = f"https:{href}"
    if "duckduckgo.com/l/?" not in href:
        return href if href.startswith("http") else ""
    target = parse_qs(urlsplit(href).query).get("uddg", [""])[0]
    return target if target.startswith("http") else ""


#: Legacy name for :func:`search_google_search`.
search_google_ground = search_google_search


def search_context(query: str, spec: SearcherSpec) -> list:
    """Context.dev web search (``POST /web/search``, bearer auth)."""
    token = env_key(spec)
    if not token:
        return []
    root = env_base(spec) or "https://api.context.dev/v1"
    data = call_json(
        "POST",
        f"{root}/web/search",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json_body={"query": query, "numResults": 10},
    )
    if data is None:
        return []
    return hits_from_maps(
        dig(data, "results"), spec.id, title="title", url="url", snippet="description"
    )


_DDG_MCP_RESULT = re.compile(
    r"^\s*\d+\.\s*(?P<title>.+?)\s*\n\s*URL:\s*(?P<url>https?://\S+)\s*(?:\n\s*Summary:\s*(?P<snippet>.*?))?(?=\n\s*\d+\.\s|\Z)",
    re.MULTILINE | re.DOTALL,
)


def _ddg_mcp_hits(payload: object, searcher_id: str) -> list:
    """Normalize a DuckDuckGo MCP ``search`` result (JSON rows or numbered text)."""
    if isinstance(payload, dict):
        for field in ("results", "data", "organic"):
            if field in payload:
                return _ddg_mcp_hits(payload[field], searcher_id)
        return []
    if isinstance(payload, list):
        return hits_from_maps(
            [
                {
                    "title": r.get("title"),
                    "url": r.get("url") or r.get("href") or r.get("link"),
                    "snippet": r.get("snippet") or r.get("body") or r.get("summary") or "",
                }
                for r in payload
                if isinstance(r, dict)
            ],
            searcher_id,
            title="title",
            url="url",
            snippet="snippet",
        )
    if isinstance(payload, str):
        rows = [
            {
                "title": m["title"].strip(),
                "url": m["url"],
                "snippet": " ".join((m["snippet"] or "").split()),
            }
            for m in _DDG_MCP_RESULT.finditer(payload)
        ]
        if not rows:
            rows = [
                {
                    "title": m["title"].strip(),
                    "url": m["url"],
                    "snippet": " ".join(m["snippet"].split()),
                }
                for m in _DDG_MCP_MARKDOWN.finditer(payload)
            ]
        return hits_from_maps(rows, searcher_id, title="title", url="url", snippet="snippet")
    return []


#: ``duckduckgo-mcp-server`` (npm, zhsama) formats hits as ``### title / text / 🔗 [..](url)``.
_DDG_MCP_MARKDOWN = re.compile(
    r"###\s*(?P<title>[^\n]+)\n(?P<snippet>.*?)\n\s*🔗\s*\[[^\]]*\]\((?P<url>https?://[^)\s]+)\)",
    re.DOTALL,
)

#: Pinned, reviewed release of the stdio server (MIT, no install scripts; sources read 2026-10-08).
_DDG_MCP_STDIO_ARGS = ("-y", "duckduckgo-mcp-server@0.1.2")


def _clean_path() -> str:
    """``PATH`` without mise/pixi shims so the stdio server runs on the system Node."""
    parts = os.environ.get("PATH", "").split(os.pathsep)
    return os.pathsep.join(
        p for p in parts if "/.local/share/mise/" not in p and "/.pixi/" not in p
    )


async def _ddg_mcp_search(target: str | StdioServerParameters, query: str) -> object:
    """Call a DuckDuckGo MCP server's search tool (streamable HTTP URL or stdio params)."""
    from mcp import Client

    async with Client(target) as client:
        tools = {t.name for t in (await client.list_tools()).tools}
        zhsama = next(
            (n for n in ("duckduckgo_web_search", "duckduckgo_search") if n in tools), None
        )
        if zhsama:
            name, args = zhsama, {"query": query, "count": 8}
        else:
            name, args = "search", {"query": query, "max_results": 8}
        result = await client.call_tool(name, args)
    if result.is_error:
        return None
    if result.structured_content is not None:
        return result.structured_content
    for block in result.content:
        value = getattr(block, "text", None)
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
    return None


def search_ddg_mcp(query: str, spec: SearcherSpec) -> list:
    """Search through a DuckDuckGo MCP server.

    ``DDG_MCP_URL`` (via ``base_url_env``) selects a streamable-HTTP server. With no URL and
    ``engine: stdio`` the pinned ``duckduckgo-mcp-server`` is spawned over stdio instead.
    """
    url = env_base(spec)
    target: str | StdioServerParameters
    if url:
        target = url
    elif spec.engine == "stdio":
        from mcp import StdioServerParameters

        target = StdioServerParameters(
            command="/usr/local/bin/npx",
            args=list(_DDG_MCP_STDIO_ARGS),
            env={**os.environ, "PATH": _clean_path()},
        )
    else:
        return []
    try:
        payload = asyncio.run(_ddg_mcp_search(target, query))
    except Exception:  # noqa: BLE001 - provider boundary: a dead MCP server yields no hits
        return []
    return _ddg_mcp_hits(payload, spec.id)
