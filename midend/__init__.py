"""Midend: crawl URLs then scrape HTML.

Crawlers (httpx, scrapy, playwright, crawlee) are tried in ``providers.yaml`` order and
missing crawler extras fail closed, so the next crawler runs. ``crawl_then_scrape`` crawls
search hits concurrently and decodes them into ``ScrapedPage`` records; only ``http``/``https``
URLs are allowed and duplicates are dropped before the URL cap.
"""

from __future__ import annotations

import asyncio
import importlib
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
from WebSearch.repeater import normalize_url, repeater

# --- crawlers ------------------------------------------------------------------


def ordered_fetch(url: str, *, crawl: CrawlSpec | None = None) -> tuple[bytes, CrawlerName]:
    """Try crawlers in ``crawler_order`` until one returns bytes.

    Args:
        url (str): Absolute http(s) URL.
        crawl (CrawlSpec | None): Timeouts and order; default from yaml.

    Returns:
        tuple[bytes, CrawlerName]: Body and which crawler succeeded.

    Raises:
        OSError: If every crawler fails (import, network, or empty body).
    """
    spec = crawl or load_providers().crawl
    last: BaseException | None = None
    for name in spec.crawler_order:
        try:
            return _fetch_named(name, url, spec.timeout_s), name
        except (TimeoutError, OSError, ConnectionError, ImportError) as exc:
            last = exc
    raise OSError(str(last) if last is not None else "all crawlers failed") from last


def _fetch_named(name: CrawlerName, url: str, timeout_s: float) -> bytes:
    """Dispatch a fetch to the crawler named in ``providers.yaml``.

    Args:
        name: Crawler identifier from the yaml registry.
        url: Absolute http(s) URL.
        timeout_s: Per-crawler timeout in seconds.

    Returns:
        bytes: Response body.

    Raises:
        OSError: If the named crawler is unavailable or the fetch fails.
    """
    if name == "httpx":
        return default_fetch(url, timeout_s=timeout_s)
    if name == "scrapy":
        return fetch_scrapy(url, timeout_s=timeout_s)
    if name == "playwright":
        return fetch_playwright(url, timeout_s=timeout_s)
    return fetch_crawlee(url, timeout_s=timeout_s)


@repeater.s
def default_fetch(url: str, *, timeout_s: float = 20.0) -> bytes:
    """HTTP GET via httpx.

    Args:
        url (str): Absolute URL.
        timeout_s (float): Request timeout in seconds.

    Returns:
        bytes: Response body.

    Raises:
        TimeoutError, OSError, ConnectionError: After retries / HTTP errors.
    """
    try:
        import httpx
    except ImportError as exc:
        raise OSError("httpx not installed") from exc

    try:
        response = httpx.get(url, timeout=timeout_s, follow_redirects=True)
        response.raise_for_status()
        return bytes(response.content)
    except httpx.HTTPError as exc:
        raise OSError(str(exc)) from exc


@repeater.s
def fetch_scrapy(url: str, *, timeout_s: float = 20.0) -> bytes:
    """Fetch using Scrapy types after a GET. Fails if scrapy is not installed.

    Args:
        url (str): Absolute URL.
        timeout_s (float): Timeout for the inner GET.

    Returns:
        bytes: Response body wrapped as ``HtmlResponse``.

    Raises:
        OSError: Missing scrapy or fetch failure.
    """
    try:
        scrapy_http = importlib.import_module("scrapy.http")
    except ImportError as exc:
        raise OSError("scrapy not installed") from exc
    html_response = scrapy_http.HtmlResponse
    raw = default_fetch(url, timeout_s=timeout_s)
    html_response(url=url, body=raw, encoding="utf-8")
    return raw


@repeater.s
def fetch_playwright(url: str, *, timeout_s: float = 20.0) -> bytes:
    """Headless Chromium GET via Playwright. Fails if playwright is missing.

    Args:
        url (str): Absolute URL.
        timeout_s (float): Navigation timeout in seconds.

    Returns:
        bytes: ``page.content()`` encoded as UTF-8.

    Raises:
        OSError: Missing playwright, browser, or navigation error.
    """
    try:
        sync_api = importlib.import_module("playwright.sync_api")
    except ImportError as exc:
        raise OSError("playwright not installed") from exc
    playwright_error = sync_api.Error
    try:
        with sync_api.sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=int(timeout_s * 1000), wait_until="domcontentloaded")
            html = page.content()
            browser.close()
        return html.encode("utf-8")
    except playwright_error as exc:
        raise OSError(str(exc)) from exc


@repeater.s
def fetch_crawlee(url: str, *, timeout_s: float = 20.0) -> bytes:
    """Single-URL fetch via Crawlee HttpCrawler. Fails if crawlee is missing.

    Args:
        url (str): Absolute URL.
        timeout_s (float): Unused if the crawler has its own timeouts.

    Returns:
        bytes: Handler-captured body.

    Raises:
        OSError: Missing crawlee, empty body, or runtime error.
    """
    del timeout_s
    try:
        crawlee_crawlers = importlib.import_module("crawlee.crawlers")
    except ImportError as exc:
        raise OSError("crawlee not installed") from exc

    captured: list[bytes] = []
    http_crawler = crawlee_crawlers.HttpCrawler

    async def _run() -> None:
        crawler = http_crawler()

        @crawler.router.default_handler
        async def handler(ctx: object) -> None:
            http_response = getattr(ctx, "http_response", None)
            if http_response is None:
                return
            payload = await http_response.read()
            captured.append(bytes(payload))

        await crawler.run([url])

    try:
        asyncio.run(_run())
    except RuntimeError as exc:
        raise OSError(str(exc)) from exc
    if not captured:
        raise OSError("crawlee empty body")
    return captured[0]


# --- scrape --------------------------------------------------------------------

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
        return ScrapedPage(url=url, html="", status=0, error=type(exc).__name__, elapsed_ms=elapsed)
    html = raw[: crawl.max_bytes].decode("utf-8-sig", errors="replace")
    elapsed = (time.perf_counter() - start) * 1000
    return ScrapedPage(url=url, html=html, status=200, crawler=crawler, elapsed_ms=elapsed)


__all__ = [
    "FetchFn",
    "ScrapedPage",
    "crawl_then_scrape",
    "default_fetch",
    "fetch_crawlee",
    "fetch_playwright",
    "fetch_scrapy",
    "ordered_fetch",
    "type_is_http_url",
]
