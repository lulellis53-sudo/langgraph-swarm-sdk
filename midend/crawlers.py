"""Crawlers (httpx, scrapy, playwright, crawlee) tried in ``providers.yaml`` order."""

from __future__ import annotations

import asyncio
import importlib

from WebSearch.frontend.providers import CrawlerName, CrawlSpec, load_providers
from WebSearch.repeater import repeater


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


__all__ = [
    "default_fetch",
    "fetch_crawlee",
    "fetch_playwright",
    "fetch_scrapy",
    "ordered_fetch",
]
