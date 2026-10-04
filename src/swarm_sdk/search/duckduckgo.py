"""
DuckDuckGo Search Engine & Page Extractor.
High-performance asynchronous scraper using httpx, selectolax, and trafilatura.
Zero external API key dependencies.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx
import trafilatura
from selectolax.parser import HTMLParser

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://duckduckgo.com/",
}

TIME_RANGE_MAP = {
    "day": "d",
    "week": "w",
    "month": "m",
    "year": "y",
}


async def duckduckgo_search(
    query: str,
    max_results: int = 10,
    time_range: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, str]]:
    """Executes an asynchronous web search on DuckDuckGo HTML endpoint.

    Args:
        query: Search query string.
        max_results: Maximum results to return (default: 10).
        time_range: Optional time filter ('day', 'week', 'month', 'year').
        client: Optional shared httpx.AsyncClient.

    Returns:
        List of dicts with 'title', 'url', and 'snippet'.
    """
    post_data: dict[str, str] = {"q": query, "b": ""}
    if time_range and time_range.lower() in TIME_RANGE_MAP:
        post_data["df"] = TIME_RANGE_MAP[time_range.lower()]

    should_close = False
    if client is None:
        client = httpx.AsyncClient(headers=DEFAULT_HEADERS, follow_redirects=True, timeout=12.0)
        should_close = True

    try:
        response = await client.post("https://html.duckduckgo.com/html/", data=post_data)
        if response.status_code != 200:
            return []

        tree = HTMLParser(response.text)
        results: list[dict[str, str]] = []

        for node in tree.css(".result"):
            if len(results) >= max_results:
                break

            a_tag = node.css_first(".result__title a")
            snippet_node = node.css_first(".result__snippet")
            if not a_tag:
                continue

            raw_href = a_tag.attributes.get("href") or ""
            if "uddg=" in raw_href:
                parsed = parse_qs(urlparse(raw_href).query)
                clean_url = unquote(parsed.get("uddg", [raw_href])[0])
            else:
                clean_url = raw_href

            title = a_tag.text(strip=True)
            snippet = snippet_node.text(strip=True) if snippet_node else ""

            if clean_url and title:
                results.append(
                    {
                        "title": title,
                        "url": clean_url,
                        "snippet": snippet,
                    }
                )

        return results
    finally:
        if should_close:
            await client.aclose()


async def duckduckgo_instant_answer(
    query: str,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Queries official DuckDuckGo Instant Answer API for encyclopedic/entity data.

    Args:
        query: Entity or question string.
        client: Optional shared httpx.AsyncClient.

    Returns:
        Structured dict with heading, abstract, source, and related topics.
    """
    params = {
        "q": query,
        "format": "json",
        "no_html": "1",
        "skip_disambig": "1",
    }
    should_close = False
    if client is None:
        client = httpx.AsyncClient(headers=DEFAULT_HEADERS, timeout=8.0)
        should_close = True

    try:
        response = await client.get("https://api.duckduckgo.com/", params=params)
        if response.status_code != 200:
            return {"error": f"HTTP {response.status_code}"}

        data = response.json()
        related = [
            t.get("Text")
            for t in data.get("RelatedTopics", [])
            if isinstance(t, dict) and "Text" in t
        ]

        return {
            "heading": data.get("Heading", ""),
            "abstract": data.get("AbstractText", ""),
            "abstract_source": data.get("AbstractSource", ""),
            "abstract_url": data.get("AbstractURL", ""),
            "entity": data.get("Entity", ""),
            "related_topics": related[:5],
        }
    finally:
        if should_close:
            await client.aclose()


async def extract_webpage_content(
    url: str,
    max_length: int = 8000,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Fetches a URL and extracts clean article/documentation markdown using trafilatura.

    Args:
        url: Target web address.
        max_length: Maximum character length to return.
        client: Optional shared httpx.AsyncClient.

    Returns:
        Dict with title, cleaned text content, and status.
    """
    should_close = False
    if client is None:
        client = httpx.AsyncClient(headers=DEFAULT_HEADERS, follow_redirects=True, timeout=12.0)
        should_close = True

    try:
        response = await client.get(url)
        if response.status_code != 200:
            return {"url": url, "error": f"Failed with status code {response.status_code}"}

        extracted_text = trafilatura.extract(
            response.text,
            include_links=True,
            include_formatting=True,
            include_tables=True,
        )

        tree = HTMLParser(response.text)
        title_node = tree.css_first("title")
        title = title_node.text(strip=True) if title_node else ""

        content = extracted_text or ""
        if len(content) > max_length:
            content = content[:max_length] + "\n... [content truncated]"

        return {
            "url": url,
            "title": title,
            "content": content,
            "length": len(content),
        }
    except Exception as e:
        return {"url": url, "error": str(e)}
    finally:
        if should_close:
            await client.aclose()
