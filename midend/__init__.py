"""Midend: crawl URLs then scrape HTML.

Crawlers (httpx, httpx2, requests, aiohttp, curl_cffi, scrapy, playwright, crawlee) are tried
in ``providers.yaml`` order and
missing crawler extras fail closed, so the next crawler runs. ``crawl_then_scrape`` crawls
search hits concurrently and decodes them into ``ScrapedPage`` records; only ``http``/``https``
URLs are allowed and duplicates are dropped before the URL cap.
"""

from __future__ import annotations

import asyncio
import importlib
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from types import ModuleType
from typing import TYPE_CHECKING, Protocol
from urllib.parse import urlparse

from WebSearch.frontend.websearchers import (
    CrawlerName,
    CrawlSpec,
    ProvidersConfig,
    SearchHit,
    load_providers,
    shared_executor,
    shared_http_client,
)
from WebSearch.repeater import normalize_url, repeater

if TYPE_CHECKING:
    from playwright.sync_api import Browser

# --- crawlers ------------------------------------------------------------------


def ordered_fetch(
    url: str,
    *,
    crawl: CrawlSpec | None = None,
    public_only: bool = False,
    resolver: Resolver | None = None,
) -> tuple[bytes, CrawlerName]:
    """Try crawlers in ``crawler_order`` until one returns bytes.

    Args:
        url (str): Absolute http(s) URL.
        crawl (CrawlSpec | None): Timeouts and order; default from yaml.
        public_only: Refuse a non-public host before any crawler runs. A redirect
            onto a private host (``PrivateTarget``) does not fall through to the
            next crawler.
        resolver: Host resolver for ``public_only``. ``None`` uses the system resolver.

    Returns:
        tuple[bytes, CrawlerName]: Body and which crawler succeeded.

    Raises:
        PrivateTarget: ``public_only`` and the URL or an httpx redirect hop is not public.
        OSError: If every crawler fails (import, network, or empty body).
    """
    if public_only:
        _require_public(url, resolver)
    spec = crawl or load_providers().crawl
    last: BaseException | None = None
    for name in spec.crawler_order:
        try:
            return (
                _fetch_named(
                    name,
                    url,
                    spec.timeout_s,
                    max_bytes=spec.max_bytes,
                    public_only=public_only,
                    resolver=resolver,
                ),
                name,
            )
        except PrivateTarget:
            raise
        except (TimeoutError, OSError, ConnectionError, ImportError) as exc:
            last = exc
    raise OSError(str(last) if last is not None else "all crawlers failed") from last


def _fetch_named(
    name: CrawlerName,
    url: str,
    timeout_s: float,
    *,
    max_bytes: int | None = None,
    public_only: bool = False,
    resolver: Resolver | None = None,
) -> bytes:
    """Dispatch a fetch to the crawler named in ``providers.yaml``.

    Args:
        name: Crawler identifier from the yaml registry.
        url: Absolute http(s) URL.
        timeout_s: Per-crawler timeout in seconds.
        max_bytes: Retained-body cap; only the httpx crawler applies it.

    Returns:
        bytes: Response body.

    Raises:
        OSError: If the named crawler is unavailable or the fetch fails.
    """
    if name == "httpx":
        return default_fetch(
            url,
            timeout_s=timeout_s,
            max_bytes=max_bytes,
            public_only=public_only,
            resolver=resolver,
        )
    if name == "httpx2":
        return fetch_httpx2(url, timeout_s=timeout_s, max_bytes=max_bytes)
    if name == "requests":
        return fetch_requests(url, timeout_s=timeout_s, max_bytes=max_bytes)
    if name == "aiohttp":
        return fetch_aiohttp(url, timeout_s=timeout_s, max_bytes=max_bytes)
    if name == "curl_cffi":
        return fetch_curl_cffi(url, timeout_s=timeout_s, max_bytes=max_bytes)
    if name == "scrapy":
        return fetch_scrapy(url, timeout_s=timeout_s, public_only=public_only, resolver=resolver)
    if name == "playwright":
        return fetch_playwright(
            url, timeout_s=timeout_s, public_only=public_only, resolver=resolver
        )
    return fetch_crawlee(url, timeout_s=timeout_s)


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


@repeater.s
def default_fetch(
    url: str,
    *,
    timeout_s: float = 20.0,
    max_bytes: int | None = None,
    public_only: bool = False,
    resolver: Resolver | None = None,
) -> bytes:
    """HTTP GET via the shared httpx client.

    Args:
        url (str): Absolute URL.
        timeout_s (float): Request timeout in seconds.
        max_bytes (int | None): Cap on retained body bytes; ``None`` keeps all.
        public_only: Check the URL and each redirect hop. A private hop raises
            ``PrivateTarget`` and does not read the body.
        resolver: Host resolver for ``public_only``. ``None`` uses the system resolver.

    Returns:
        bytes: Response body, at most ``max_bytes`` when capped.

    Raises:
        PrivateTarget: ``public_only`` and a hop is not a public http(s) host.
        TimeoutError, OSError, ConnectionError: After retries / HTTP errors.
    """
    try:
        import httpx
    except ImportError as exc:
        raise OSError("httpx not installed") from exc

    try:
        if not public_only:
            with shared_http_client().stream(
                "GET", url, timeout=timeout_s, follow_redirects=True
            ) as response:
                response.raise_for_status()
                return _read_stream(response, max_bytes)
        current = url
        for _ in range(_MAX_REDIRECTS + 1):
            _require_public(current, resolver)
            with shared_http_client().stream(
                "GET", current, timeout=timeout_s, follow_redirects=False
            ) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise OSError("redirect missing location")
                    current = str(httpx.URL(current).join(location))
                    continue
                response.raise_for_status()
                return _read_stream(response, max_bytes)
        raise PrivateTarget("too many redirects")
    except PrivateTarget:
        raise
    except httpx.HTTPError as exc:
        raise OSError(str(exc)) from exc


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
    from WebSearch.browse_agent import is_public_http_url

    kwargs: dict[str, Resolver] = {} if resolver is None else {"resolver": resolver}
    if not is_public_http_url(url, **kwargs):
        raise PrivateTarget("non-public host refused")


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


@repeater.s
def fetch_httpx2(url: str, *, timeout_s: float = 20.0, max_bytes: int | None = None) -> bytes:
    """HTTP GET via ``httpx2`` (the pydantic/httpx2 successor to httpx).

    Raises:
        OSError: Missing ``httpx2``, HTTP error status, or network failure.
    """
    try:
        httpx2 = importlib.import_module("httpx2")
    except ImportError as exc:
        raise OSError("httpx2 not installed") from exc
    try:
        with (
            httpx2.Client(
                timeout=timeout_s, follow_redirects=True, headers={"User-Agent": _USER_AGENT}
            ) as client,
            client.stream("GET", url) as response,
        ):
            response.raise_for_status()
            return _capped(response.iter_bytes(), max_bytes)
    except httpx2.HTTPError as exc:
        raise OSError(str(exc)) from exc


@repeater.s
def fetch_requests(url: str, *, timeout_s: float = 20.0, max_bytes: int | None = None) -> bytes:
    """HTTP GET via ``requests`` (streamed, so ``max_bytes`` limits the download).

    Raises:
        OSError: Missing ``requests``, HTTP error status, or network failure.
    """
    try:
        requests = importlib.import_module("requests")
    except ImportError as exc:
        raise OSError("requests not installed") from exc
    try:
        with requests.get(
            url, timeout=timeout_s, stream=True, headers={"User-Agent": _USER_AGENT}
        ) as response:
            response.raise_for_status()
            return _capped(response.iter_content(chunk_size=65536), max_bytes)
    except requests.RequestException as exc:
        raise OSError(str(exc)) from exc


@repeater.s
def fetch_aiohttp(url: str, *, timeout_s: float = 20.0, max_bytes: int | None = None) -> bytes:
    """HTTP GET via ``aiohttp``, run to completion on its own event loop in this thread.

    Raises:
        OSError: Missing ``aiohttp``, HTTP error status, timeout, or network failure.
    """
    try:
        aiohttp = importlib.import_module("aiohttp")
    except ImportError as exc:
        raise OSError("aiohttp not installed") from exc

    async def _get() -> bytes:
        timeout = aiohttp.ClientTimeout(total=timeout_s)
        async with (
            aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": _USER_AGENT}) as session,
            session.get(url) as response,
        ):
            response.raise_for_status()
            chunks = [chunk async for chunk in response.content.iter_chunked(65536)]
            return _capped(chunks, max_bytes)

    try:
        return asyncio.run(_get())
    except (aiohttp.ClientError, TimeoutError) as exc:
        raise OSError(str(exc) or type(exc).__name__) from exc


@repeater.s
def fetch_curl_cffi(url: str, *, timeout_s: float = 20.0, max_bytes: int | None = None) -> bytes:
    """HTTP GET via ``curl_cffi`` with a Chrome TLS/HTTP2 fingerprint.

    Gets past sites that reject the TLS handshake of plain Python HTTP clients.

    Raises:
        OSError: Missing ``curl_cffi``, HTTP error status, or network failure.
    """
    try:
        cffi_requests = importlib.import_module("curl_cffi.requests")
    except ImportError as exc:
        raise OSError("curl_cffi not installed") from exc
    try:
        response = cffi_requests.get(url, impersonate="chrome", timeout=timeout_s)
        response.raise_for_status()
    except cffi_requests.RequestsError as exc:
        raise OSError(str(exc)) from exc
    return response.content if max_bytes is None else response.content[:max_bytes]


@repeater.s
def fetch_scrapy(
    url: str,
    *,
    timeout_s: float = 20.0,
    public_only: bool = False,
    resolver: Resolver | None = None,
) -> bytes:
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
    raw = default_fetch(url, timeout_s=timeout_s, public_only=public_only, resolver=resolver)
    html_response(url=url, body=raw, encoding="utf-8")
    return raw


_PLAYWRIGHT_LOCAL = threading.local()


def _thread_browser(sync_api: ModuleType) -> Browser:
    """Start one Chromium per worker thread; sync API objects are thread-bound."""
    browser = getattr(_PLAYWRIGHT_LOCAL, "browser", None)
    if browser is not None and browser.is_connected():
        return browser
    old_pw = getattr(_PLAYWRIGHT_LOCAL, "pw", None)
    if old_pw is not None:
        old_pw.stop()
    pw = sync_api.sync_playwright().start()
    _PLAYWRIGHT_LOCAL.pw = pw
    _PLAYWRIGHT_LOCAL.browser = pw.chromium.launch(headless=True)
    return _PLAYWRIGHT_LOCAL.browser


@repeater.s
def fetch_playwright(
    url: str,
    *,
    timeout_s: float = 20.0,
    public_only: bool = True,
    resolver: Resolver | None = None,
) -> bytes:
    """Headless Chromium GET via Playwright. Fails if playwright is missing.

    The browser starts once per worker thread and is reused across calls; the
    sync API is thread-bound, so a shared browser would raise cross-thread.

    Args:
        url (str): Absolute URL.
        timeout_s (float): Navigation timeout in seconds.
        public_only: After navigation, refuse a final URL that is not public http(s).
            Default on: ``browse`` and cowork use this function directly.
        resolver: Host resolver for that check. ``None`` uses the system resolver.

    Returns:
        bytes: ``page.content()`` encoded as UTF-8.

    Raises:
        PrivateTarget: ``public_only`` and the landed URL is not public.
        OSError: Missing playwright, browser, or navigation error.
    """
    try:
        sync_api = importlib.import_module("playwright.sync_api")
    except ImportError as exc:
        raise OSError("playwright not installed") from exc
    try:
        stealth = importlib.import_module("playwright_stealth")
        stealth_sync = getattr(stealth, "stealth_sync", None)
    except ImportError:
        stealth_sync = None
    playwright_error = sync_api.Error
    try:
        browser = _thread_browser(sync_api)
        page = browser.new_page()
        try:
            if stealth_sync is not None:
                stealth_sync(page)
            page.goto(url, timeout=int(timeout_s * 1000), wait_until="domcontentloaded")
            if public_only:
                _require_public(page.url, resolver)
            html = page.content()
        finally:
            page.close()
        return html.encode("utf-8")
    except playwright_error as exc:
        browser = getattr(_PLAYWRIGHT_LOCAL, "browser", None)
        if browser is not None and not browser.is_connected():
            _PLAYWRIGHT_LOCAL.browser = None
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
            return ordered_fetch(url, crawl=crawl, public_only=True)

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
    semaphore = threading.Semaphore(max(1, min(max_workers, len(urls))))

    def capped(url: str) -> tuple[bytes, CrawlerName | None]:
        with semaphore:
            return getter(url)

    pool = shared_executor()
    return list(pool.map(lambda u: _scrape_one(u, fetch=capped, crawl=crawl), urls))


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
    except PrivateTarget as exc:
        elapsed = (time.perf_counter() - start) * 1000
        return ScrapedPage(
            url=url, html="", status=0, error=type(exc).__name__, elapsed_ms=elapsed
        )
    except (TimeoutError, OSError, ConnectionError) as exc:
        elapsed = (time.perf_counter() - start) * 1000
        return ScrapedPage(url=url, html="", status=0, error=type(exc).__name__, elapsed_ms=elapsed)
    html = raw[: crawl.max_bytes].decode("utf-8-sig", errors="replace")
    elapsed = (time.perf_counter() - start) * 1000
    return ScrapedPage(url=url, html=html, status=200, crawler=crawler, elapsed_ms=elapsed)


__all__ = [
    "FetchFn",
    "PrivateTarget",
    "ScrapedPage",
    "crawl_then_scrape",
    "default_fetch",
    "fetch_crawlee",
    "fetch_playwright",
    "fetch_scrapy",
    "ordered_fetch",
    "type_is_http_url",
]
