"""WebSearch pipeline: frontend searchers → midend crawl/scrape → backend extract."""

from __future__ import annotations

from collections.abc import Mapping
from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from WebSearch.backend import ExtractedDoc
    from WebSearch.frontend.dorks import DorkError
    from WebSearch.frontend.websearchers import (
        ProvidersConfig,
        SearchFn,
        SearchHit,
    )
    from WebSearch.midend import FetchFn, ScrapedPage

_EXPORTS: dict[str, tuple[str, str]] = {
    "DorkError": ("WebSearch.frontend.dorks", "DorkError"),
    "ExtractedDoc": ("WebSearch.backend", "ExtractedDoc"),
    "FetchFn": ("WebSearch.midend", "FetchFn"),
    "ProvidersConfig": ("WebSearch.frontend.websearchers", "ProvidersConfig"),
    "ScrapedPage": ("WebSearch.midend", "ScrapedPage"),
    "SearchFn": ("WebSearch.frontend.websearchers", "SearchFn"),
    "SearchHit": ("WebSearch.frontend.websearchers", "SearchHit"),
    "any_of": ("WebSearch.frontend.dorks", "any_of"),
    "crawl_then_scrape": ("WebSearch.midend", "crawl_then_scrape"),
    "dedupe_docs": ("WebSearch.backend", "dedupe_docs"),
    "dork": ("WebSearch.frontend.dorks", "dork"),
    "extract_and_normalize": ("WebSearch.backend", "extract_and_normalize"),
    "load_providers": ("WebSearch.frontend.websearchers", "load_providers"),
    "builtin_searchers": ("WebSearch.frontend.websearchers", "builtin_searchers"),
    "parallel_search": ("WebSearch.frontend.websearchers", "parallel_search"),
    "registry_search": ("WebSearch.frontend.websearchers", "registry_search"),
    "render_brief": ("WebSearch.agent_tools", "render_brief"),
    "search_brief": ("WebSearch.agent_tools", "search_brief"),
    "search_hits": ("WebSearch.agent_tools", "search_hits"),
    "dedupe_documents": ("WebSearch.agent_tools", "dedupe_documents"),
    "summarize_documents": ("WebSearch.agent_tools", "summarize_documents"),
    "websearch_langchain_tools": ("WebSearch.langchain_tools", "websearch_langchain_tools"),
    "run_cowork_pipeline": ("WebSearch.browser_agent", "run_cowork_pipeline"),
}


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
    from WebSearch.backend import extract_and_normalize
    from WebSearch.frontend.websearchers import (
        _SEARCH_CACHE_TTL_S,
        builtin_searchers,
        load_providers,
        parallel_search,
        registry_search,
    )
    from WebSearch.midend import crawl_then_scrape

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


def __getattr__(name: str) -> Any:
    """Load public names on first access so ``import WebSearch`` stays light."""
    if name == "agent_tools":
        mod = import_module("WebSearch.agent_tools")
        globals()["agent_tools"] = mod
        return mod
    spec = _EXPORTS.get(name)
    if spec is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = spec
    value = getattr(import_module(module_name), attr)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(__all__)


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
    "dedupe_documents",
    "dork",
    "extract_and_normalize",
    "load_providers",
    "builtin_searchers",
    "parallel_search",
    "registry_search",
    "run_pipeline",
    "run_cowork_pipeline",
    "render_brief",
    "search_brief",
    "search_hits",
    "summarize_documents",
    "websearch_langchain_tools",
]
