"""Midend: crawl URLs then scrape HTML.

Missing crawler extras fail closed and the next crawler runs.
"""

from __future__ import annotations

from WebSearch.midend.crawlers import (
    default_fetch,
    fetch_crawlee,
    fetch_playwright,
    fetch_scrapy,
    ordered_fetch,
)
from WebSearch.midend.scrape import FetchFn, ScrapedPage, crawl_then_scrape, type_is_http_url

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
