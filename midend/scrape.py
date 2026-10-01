"""Crawl search hits concurrently and decode them into ``ScrapedPage`` records.

Only ``http``/``https`` URLs are allowed; duplicates are dropped before the URL cap.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import urlparse

from WebSearch.frontend.models import SearchHit
from WebSearch.frontend.providers import (
    CrawlerName,
    CrawlSpec,
    ProvidersConfig,
    load_providers,
)
from WebSearch.midend.crawlers import ordered_fetch
from WebSearch.repeater import normalize_url

#: Callable that fetches a URL and returns raw bytes. Used to inject test doubles.
FetchFn = Callable[[str], bytes]


#: Internal fetcher that also reports which crawler produced the bytes.
_Fetcher = Callable[[str], tuple[bytes, CrawlerName | None]]


_MAX_WORKERS = 8


@dataclass(frozen=True, slots=True)
class ScrapedPage:
    """One crawled URL plus the scraped HTML and metadata.

    Attributes:
        url: The original URL.
        html: Decoded page body (empty when ``error`` is set).
        status: HTTP-like status; ``0`` for blocked or network errors.
        error: Short error tag, or ``None`` on success.
        crawler: Name of the crawler that produced the bytes, or ``None``.
        elapsed_ms: Wall time spent fetching and decoding this URL.
    """

    url: str
    html: str
    status: int = 200
    error: str | None = None
    crawler: CrawlerName | None = None
    elapsed_ms: float = 0.0


def type_is_http_url(url: str, schemes: Sequence[str]) -> bool:
    """Return whether *url* uses an allowed scheme and has a host.

    Args:
        url (str): Candidate URL.
        schemes (Sequence[str]): Allowed schemes (e.g. http, https).

    Returns:
        bool: True if crawl is allowed.
    """
    parsed = urlparse(url)
    return parsed.scheme in schemes and bool(parsed.netloc)


def crawl_then_scrape(
    hits: Sequence[SearchHit],
    *,
    fetch: FetchFn | None = None,
    config: ProvidersConfig | None = None,
    max_workers: int = _MAX_WORKERS,
) -> list[ScrapedPage]:
    """Deduplicate hit URLs, then crawl and scrape them concurrently.

    URLs are deduplicated by canonical form *before* the ``max_urls`` cut, so
    duplicates never waste a slot. Output order follows the hit order.

    Args:
        hits (Sequence[SearchHit]): Frontend results.
        fetch (FetchFn | None): Override GET. Default tries crawlers in yaml order.
        config (ProvidersConfig | None): Crawl limits and crawler order.
        max_workers (int): Thread cap; values below 1 are clamped to 1.

    Returns:
        list[ScrapedPage]: One page per unique URL, at most ``crawl.max_urls``.
    """
    crawl = (config or load_providers()).crawl
    if fetch is not None:
        injected = fetch

        def getter(url: str) -> tuple[bytes, CrawlerName | None]:
            return injected(url), None

    else:

        def getter(url: str) -> tuple[bytes, CrawlerName | None]:
            return ordered_fetch(url, crawl=crawl)

    seen: set[str] = set()
    urls: list[str] = []
    for hit in hits:
        key = normalize_url(hit.url)
        if key not in seen:
            seen.add(key)
            urls.append(hit.url)
    urls = urls[: crawl.max_urls]
    if not urls:
        return []
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(urls)))) as pool:
        return list(pool.map(lambda u: _scrape_one(u, fetch=getter, crawl=crawl), urls))


def _scrape_one(url: str, *, fetch: _Fetcher, crawl: CrawlSpec) -> ScrapedPage:
    """Crawl and decode a single URL, applying scheme blocking and size caps.

    Args:
        url: Candidate URL.
        fetch: Low-level fetcher returning bytes and the crawler used.
        crawl: Crawl limits and allowed schemes.

    Returns:
        ScrapedPage: Success page or a failure record with an ``error`` tag.
    """
    if not type_is_http_url(url, crawl.schemes):
        return ScrapedPage(url=url, html="", status=0, error="blocked_scheme")
    start = time.perf_counter()
    try:
        raw, crawler = fetch(url)
    except (TimeoutError, OSError, ConnectionError) as exc:
        elapsed = (time.perf_counter() - start) * 1000
        return ScrapedPage(
            url=url, html="", status=0, error=type(exc).__name__, elapsed_ms=elapsed
        )
    html = raw[: crawl.max_bytes].decode("utf-8-sig", errors="replace")
    elapsed = (time.perf_counter() - start) * 1000
    return ScrapedPage(
        url=url, html=html, status=200, crawler=crawler, elapsed_ms=elapsed
    )


__all__ = ["FetchFn", "ScrapedPage", "crawl_then_scrape", "type_is_http_url"]
