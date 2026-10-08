"""Midend crawler backends: one ``fetch_*`` function per crawler named in providers.yaml."""

from __future__ import annotations

import asyncio
import importlib
import threading
from types import ModuleType
from typing import TYPE_CHECKING

from WebSearch.frontend.websearchers import (
    shared_http_client,
)
from WebSearch.repeater import repeater

if TYPE_CHECKING:
    from playwright.sync_api import Browser
from WebSearch.midend.guards import (
    _MAX_REDIRECTS,
    _USER_AGENT,
    PrivateTarget,
    Resolver,
    _capped,
    _guard_url,
    _read_stream,
    _require_public,
)


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


@repeater.s
def fetch_httpx2(
    url: str,
    *,
    timeout_s: float = 20.0,
    max_bytes: int | None = None,
    public_only: bool = False,
    resolver: Resolver | None = None,
) -> bytes:
    """HTTP GET via ``httpx2`` (the pydantic/httpx2 successor to httpx).

    Raises:
        OSError: Missing ``httpx2``, HTTP error status, or network failure.
        PrivateTarget: ``public_only`` and the URL is not a public http(s) host.
    """
    _guard_url(url, public_only, resolver)
    try:
        httpx2 = importlib.import_module("httpx2")
    except ImportError as exc:
        raise OSError("httpx2 not installed") from exc
    try:
        with (
            httpx2.Client(
                timeout=timeout_s,
                follow_redirects=not public_only,
                headers={"User-Agent": _USER_AGENT},
            ) as client,
            client.stream("GET", url) as response,
        ):
            response.raise_for_status()
            return _capped(response.iter_bytes(), max_bytes)
    except httpx2.HTTPError as exc:
        raise OSError(str(exc)) from exc


@repeater.s
def fetch_requests(
    url: str,
    *,
    timeout_s: float = 20.0,
    max_bytes: int | None = None,
    public_only: bool = False,
    resolver: Resolver | None = None,
) -> bytes:
    """HTTP GET via ``requests`` (streamed, so ``max_bytes`` limits the download).

    Raises:
        OSError: Missing ``requests``, HTTP error status, or network failure.
        PrivateTarget: ``public_only`` and the URL is not a public http(s) host.
    """
    _guard_url(url, public_only, resolver)
    try:
        requests = importlib.import_module("requests")
    except ImportError as exc:
        raise OSError("requests not installed") from exc
    try:
        with requests.get(
            url,
            timeout=timeout_s,
            stream=True,
            allow_redirects=not public_only,
            headers={"User-Agent": _USER_AGENT},
        ) as response:
            response.raise_for_status()
            return _capped(response.iter_content(chunk_size=65536), max_bytes)
    except requests.RequestException as exc:
        raise OSError(str(exc)) from exc


@repeater.s
def fetch_aiohttp(
    url: str,
    *,
    timeout_s: float = 20.0,
    max_bytes: int | None = None,
    public_only: bool = False,
    resolver: Resolver | None = None,
) -> bytes:
    """HTTP GET via ``aiohttp``, run to completion on its own event loop in this thread.

    Raises:
        OSError: Missing ``aiohttp``, HTTP error status, timeout, or network failure.
        PrivateTarget: ``public_only`` and the URL is not a public http(s) host.
    """
    _guard_url(url, public_only, resolver)
    try:
        aiohttp = importlib.import_module("aiohttp")
    except ImportError as exc:
        raise OSError("aiohttp not installed") from exc

    async def _get() -> bytes:
        timeout = aiohttp.ClientTimeout(total=timeout_s)
        async with (
            aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": _USER_AGENT}) as session,
            session.get(url, allow_redirects=not public_only) as response,
        ):
            response.raise_for_status()
            chunks = [chunk async for chunk in response.content.iter_chunked(65536)]
            return _capped(chunks, max_bytes)

    try:
        return asyncio.run(_get())
    except (aiohttp.ClientError, TimeoutError) as exc:
        raise OSError(str(exc) or type(exc).__name__) from exc


@repeater.s
def fetch_curl_cffi(
    url: str,
    *,
    timeout_s: float = 20.0,
    max_bytes: int | None = None,
    public_only: bool = False,
    resolver: Resolver | None = None,
) -> bytes:
    """HTTP GET via ``curl_cffi`` with a Chrome TLS/HTTP2 fingerprint.

    Gets past sites that reject the TLS handshake of plain Python HTTP clients.

    Raises:
        OSError: Missing ``curl_cffi``, HTTP error status, or network failure.
        PrivateTarget: ``public_only`` and the URL is not a public http(s) host.
    """
    _guard_url(url, public_only, resolver)
    try:
        cffi_requests = importlib.import_module("curl_cffi.requests")
    except ImportError as exc:
        raise OSError("curl_cffi not installed") from exc
    try:
        response = cffi_requests.get(
            url,
            impersonate="chrome",
            timeout=timeout_s,
            allow_redirects=not public_only,
        )
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
    _guard_url(url, public_only, resolver)
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
    _guard_url(url, public_only, resolver)
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
def fetch_crawlee(
    url: str,
    *,
    timeout_s: float = 20.0,
    public_only: bool = False,
    resolver: Resolver | None = None,
) -> bytes:
    """Single-URL fetch via Crawlee HttpCrawler. Fails if crawlee is missing.

    Args:
        url (str): Absolute URL.
        timeout_s (float): Unused if the crawler has its own timeouts.

    Returns:
        bytes: Handler-captured body.

    Raises:
        OSError: Missing crawlee, empty body, or runtime error.
        PrivateTarget: ``public_only`` and the URL is not a public http(s) host.
    """
    del timeout_s
    _guard_url(url, public_only, resolver)
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
