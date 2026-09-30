"""WebSearch pipeline: frontend searchers → midend crawl/scrape → backend extract."""

from __future__ import annotations

from collections.abc import Mapping

from WebSearch.backend import ExtractedDoc, extract_and_normalize
from WebSearch.frontend.apis import builtin_searchers
from WebSearch.frontend.providers import ProvidersConfig, load_providers
from WebSearch.frontend.websearchers import SearchFn, SearchHit, registry_search
from WebSearch.midend import FetchFn, ScrapedPage, crawl_then_scrape


def run_pipeline(
    query: str,
    *,
    backends: Mapping[str, SearchFn] | None = None,
    fetch: FetchFn | None = None,
    config: ProvidersConfig | None = None,
    searcher_id: str | None = None,
) -> tuple[list[SearchHit], list[ScrapedPage], list[ExtractedDoc]]:
    """Search, crawl/scrape hits, then extract+normalize HTML.

    Args:
        query (str): User query.
        backends (Mapping[str, SearchFn] | None): Searcher id → fn. Default HTTP APIs.
        fetch (FetchFn | None): URL GET. Default crawler order from yaml.
        config (ProvidersConfig | None): Registry and crawl/extract settings.
        searcher_id (str | None): Pin one searcher.

    Returns:
        tuple[list[SearchHit], list[ScrapedPage], list[ExtractedDoc]]: Pipeline stages.
    """
    cfg = config or load_providers()
    table = backends if backends is not None else builtin_searchers()
    hits = list(
        registry_search(query, config=cfg, backends=table, searcher_id=searcher_id)
    )
    pages = crawl_then_scrape(hits, fetch=fetch, config=cfg)
    docs = [
        extract_and_normalize(page.html, url=page.url, config=cfg)
        for page in pages
        if page.html
    ]
    return hits, pages, docs


__all__ = [
    "ExtractedDoc",
    "FetchFn",
    "ProvidersConfig",
    "ScrapedPage",
    "SearchFn",
    "SearchHit",
    "crawl_then_scrape",
    "extract_and_normalize",
    "load_providers",
    "builtin_searchers",
    "registry_search",
    "run_pipeline",
]
