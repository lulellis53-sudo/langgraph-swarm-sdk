"""API freeze: every public name WebSearch.midend defined before it was split into modules."""

import WebSearch.midend as midend

PUBLIC = [
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


def test_public_names_survive_the_split() -> None:
    assert [name for name in PUBLIC if not hasattr(midend, name)] == []


def test_midend_all_is_importable() -> None:
    assert [name for name in midend.__all__ if not hasattr(midend, name)] == []
