"""Midend orchestration: crawler failover (``ordered_fetch``) and ``crawl_then_scrape``."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from WebSearch.frontend.websearchers import (
    CrawlerName,
    CrawlSpec,
    ProvidersConfig,
    SearchHit,
    load_providers,
    shared_executor,
)
from WebSearch.midend.politeness import Politeness, polite_fetch
from WebSearch.repeater import normalize_url

if TYPE_CHECKING:
    pass
from WebSearch.midend.crawlers import (
    default_fetch,
    fetch_aiohttp,
    fetch_crawlee,
    fetch_curl_cffi,
    fetch_httpx2,
    fetch_playwright,
    fetch_requests,
    fetch_scrapy,
)
from WebSearch.midend.guards import PrivateTarget, Resolver, _require_public


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
        return fetch_httpx2(
            url,
            timeout_s=timeout_s,
            max_bytes=max_bytes,
            public_only=public_only,
            resolver=resolver,
        )
    if name == "requests":
        return fetch_requests(
            url,
            timeout_s=timeout_s,
            max_bytes=max_bytes,
            public_only=public_only,
            resolver=resolver,
        )
    if name == "aiohttp":
        return fetch_aiohttp(
            url,
            timeout_s=timeout_s,
            max_bytes=max_bytes,
            public_only=public_only,
            resolver=resolver,
        )
    if name == "curl_cffi":
        return fetch_curl_cffi(
            url,
            timeout_s=timeout_s,
            max_bytes=max_bytes,
            public_only=public_only,
            resolver=resolver,
        )
    if name == "scrapy":
        return fetch_scrapy(url, timeout_s=timeout_s, public_only=public_only, resolver=resolver)
    if name == "playwright":
        return fetch_playwright(
            url, timeout_s=timeout_s, public_only=public_only, resolver=resolver
        )
    return fetch_crawlee(url, timeout_s=timeout_s, public_only=public_only, resolver=resolver)


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
    respect_robots: bool = True,
    politeness: Politeness | None = None,
) -> list[ScrapedPage]:
    """Deduplicate hit URLs, then crawl and scrape them concurrently.

    URLs are deduplicated by canonical form *before* the ``max_urls`` cut, so
    duplicates never waste a slot. Output order follows the hit order.

    Args:
        hits (Sequence[SearchHit]): Frontend results.
        fetch (FetchFn | None): Override GET. Default tries crawlers in yaml order.
        config (ProvidersConfig | None): Crawl limits and crawler order.
        max_workers (int): Thread cap; values below 1 are clamped to 1.
        respect_robots (bool): Honor ``robots.txt`` before fetching.
        politeness (Politeness | None): Custom politeness layer; default uses
            ``respect_robots`` and the global limits.

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

    layer = politeness if politeness is not None else Politeness(respect_robots=respect_robots)

    def polite_getter(url: str) -> tuple[bytes, CrawlerName | None]:
        return polite_fetch(url, getter, politeness=layer)

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
            return polite_getter(url)

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
        return ScrapedPage(url=url, html="", status=0, error=type(exc).__name__, elapsed_ms=elapsed)
    except (TimeoutError, OSError, ConnectionError) as exc:
        elapsed = (time.perf_counter() - start) * 1000
        return ScrapedPage(url=url, html="", status=0, error=type(exc).__name__, elapsed_ms=elapsed)
    html = raw[: crawl.max_bytes].decode("utf-8-sig", errors="replace")
    elapsed = (time.perf_counter() - start) * 1000
    return ScrapedPage(url=url, html=html, status=200, crawler=crawler, elapsed_ms=elapsed)
