"""Midend: crawl URLs then scrape HTML.

Crawlers (httpx, httpx2, requests, aiohttp, curl_cffi, scrapy, playwright, crawlee) are tried
in ``providers.yaml`` order and
missing crawler extras fail closed, so the next crawler runs. ``crawl_then_scrape`` crawls
search hits concurrently and decodes them into ``ScrapedPage`` records; only ``http``/``https``
URLs are allowed and duplicates are dropped before the URL cap.
"""

from __future__ import annotations

from WebSearch.midend.crawl import (
    FetchFn,
    ScrapedPage,
    crawl_then_scrape,
    ordered_fetch,
    type_is_http_url,
)
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
from WebSearch.midend.guards import PrivateTarget, Resolver

__all__ = [
    "FetchFn",
    "PrivateTarget",
    "Resolver",
    "ScrapedPage",
    "crawl_then_scrape",
    "default_fetch",
    "fetch_aiohttp",
    "fetch_crawlee",
    "fetch_curl_cffi",
    "fetch_httpx2",
    "fetch_playwright",
    "fetch_requests",
    "fetch_scrapy",
    "ordered_fetch",
    "type_is_http_url",
]
