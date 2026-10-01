"""WebSearch pipeline: frontend searchers → midend crawl/scrape → backend extract."""

from __future__ import annotations

from collections.abc import Mapping

from WebSearch import agent_tools
from WebSearch.agent_tools import render_brief, search_brief, search_hits
from WebSearch.backend import ExtractedDoc, dedupe_docs, extract_and_normalize
from WebSearch.frontend.dorks import DorkError, any_of, dork
from WebSearch.frontend.websearchers import (
    _SEARCH_CACHE_TTL_S,
    ProvidersConfig,
    SearchFn,
    SearchHit,
    builtin_searchers,
    load_providers,
    parallel_search,
    registry_search,
)
from WebSearch.midend import FetchFn, ScrapedPage, crawl_then_scrape


def run_pipeline(
    query: str,
    *,
    backends: Mapping[str, SearchFn] | None = None,
    fetch: FetchFn | None = None,
    config: ProvidersConfig | None = None,
    searcher_id: str | None = None,
    parallel: bool = True,
) -> tuple[list[SearchHit], list[ScrapedPage], list[ExtractedDoc]]:
    """Search, crawl/scrape hits, then extract+normalize HTML.

    Args:
        query (str): User query.
        backends (Mapping[str, SearchFn] | None): Searcher id → fn. Default HTTP APIs.
        fetch (FetchFn | None): URL GET. Default crawler order from yaml.
        config (ProvidersConfig | None): Registry and crawl/extract settings.
        searcher_id (str | None): Pin one searcher.
        parallel (bool): Query every searcher at once and merge (deduplicated);
            ``False`` uses ordered failover (first searcher with hits wins).

    Returns:
        tuple[list[SearchHit], list[ScrapedPage], list[ExtractedDoc]]: Pipeline stages.
    """
    cfg = config or load_providers()
    table = backends if backends is not None else builtin_searchers()
    if parallel:
        hits = list(
            parallel_search(
                query,
                config=cfg,
                backends=table,
                searcher_id=searcher_id,
                cache_ttl_s=_SEARCH_CACHE_TTL_S,
            )
        )
    else:
        hits = list(registry_search(query, config=cfg, backends=table, searcher_id=searcher_id))
    pages = crawl_then_scrape(hits, fetch=fetch, config=cfg)
    docs = [
        extract_and_normalize(page.html, url=page.url, config=cfg) for page in pages if page.html
    ]
    return hits, pages, docs


__all__ = [
    "DorkError",
    "ExtractedDoc",
    "FetchFn",
    "ProvidersConfig",
    "ScrapedPage",
    "SearchFn",
    "SearchHit",
    "agent_tools",
    "any_of",
    "crawl_then_scrape",
    "dedupe_docs",
    "dork",
    "extract_and_normalize",
    "load_providers",
    "builtin_searchers",
    "parallel_search",
    "registry_search",
    "run_pipeline",
    "render_brief",
    "search_brief",
    "search_hits",
]
