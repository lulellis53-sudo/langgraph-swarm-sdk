# ruff: noqa: F822
"""WebSearch package surface and ``python -m WebSearch`` entry.

Lazy public names live here so ``import WebSearch`` stays light.
"""

from __future__ import annotations

lazy from collections.abc import Mapping
lazy from importlib import import_module
lazy from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from WebSearch.Core.backend import ExtractedDoc
    from WebSearch.Core.frontend.dorks import DorkError
    from WebSearch.Core.frontend.websearchers import (
        ProvidersConfig,
        SearchFn,
        SearchHit,
    )
    from WebSearch.Core.midend import FetchFn, ScrapedPage

_EXPORTS: dict[str, tuple[str, str]] = {
    "DorkError": ("WebSearch.Core.frontend.dorks", "DorkError"),
    "ExtractedDoc": ("WebSearch.Core.backend", "ExtractedDoc"),
    "FetchFn": ("WebSearch.Core.midend", "FetchFn"),
    "ProvidersConfig": ("WebSearch.Core.frontend.websearchers", "ProvidersConfig"),
    "ScrapedPage": ("WebSearch.Core.midend", "ScrapedPage"),
    "SearchFn": ("WebSearch.Core.frontend.websearchers", "SearchFn"),
    "SearchHit": ("WebSearch.Core.frontend.websearchers", "SearchHit"),
    "any_of": ("WebSearch.Core.frontend.dorks", "any_of"),
    "crawl_then_scrape": ("WebSearch.Core.midend", "crawl_then_scrape"),
    "dedupe_docs": ("WebSearch.Core.backend", "dedupe_docs"),
    "dork": ("WebSearch.Core.frontend.dorks", "dork"),
    "extract_and_normalize": ("WebSearch.Core.backend", "extract_and_normalize"),
    "load_providers": ("WebSearch.Core.frontend.websearchers", "load_providers"),
    "builtin_searchers": ("WebSearch.Core.frontend.websearchers", "builtin_searchers"),
    "parallel_search": ("WebSearch.Core.frontend.websearchers", "parallel_search"),
    "registry_search": ("WebSearch.Core.frontend.websearchers", "registry_search"),
    "render_brief": ("WebSearch.Core.agents.agent_tools", "render_brief"),
    "search_brief": ("WebSearch.Core.agents.agent_tools", "search_brief"),
    "search_hits": ("WebSearch.Core.agents.agent_tools", "search_hits"),
    "dedupe_documents": ("WebSearch.Core.agents.agent_tools", "dedupe_documents"),
    "summarize_documents": ("WebSearch.Core.agents.agent_tools", "summarize_documents"),
    "websearch_langchain_tools": ("WebSearch.Core.agents.langchain_tools", "websearch_langchain_tools"),
    "websearch_swarm_tools": ("WebSearch.Core.agents.swarm_tools", "websearch_swarm_tools"),
    "swarm_tool_manifests": ("WebSearch.Core.agents.swarm_tools", "swarm_tool_manifests"),
    "swarm_dispatch": ("WebSearch.Core.agents.swarm_tools", "swarm_dispatch"),
    "run_cowork_pipeline": ("WebSearch.Core.app.browser_agent", "run_cowork_pipeline"),
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
    from WebSearch.Core.backend import extract_and_normalize
    from WebSearch.Core.frontend.websearchers import (
        _SEARCH_CACHE_TTL_S,
        builtin_searchers,
        load_providers,
        parallel_search,
        registry_search,
    )
    from WebSearch.Core.midend import crawl_then_scrape

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


def main() -> int:
    """CLI entry for ``python -m WebSearch``."""
    from WebSearch.Core.app.cli import main as cli_main

    return cli_main()


def __getattr__(name: str) -> Any:
    """Load public names on first access so ``import WebSearch`` stays light."""
    if name == "agent_tools":
        mod = import_module("WebSearch.Core.agents.agent_tools")
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
    """Return sorted lazy public names for ``dir(WebSearch)``."""
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
