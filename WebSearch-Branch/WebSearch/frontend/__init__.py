"""Frontend package: searchers, dorks, and hit cleanup."""

from __future__ import annotations

from WebSearch.backend.prefilter import prefilter_hits
from WebSearch.frontend.dorks import DorkError, any_of, dork
from WebSearch.frontend.hits import near_dedupe, normalize_hit
from WebSearch.frontend.websearchers import (
    CrawlerName,
    CrawlSpec,
    ExtractorName,
    NullSink,
    PrefilterPolicy,
    ProvidersConfig,
    ResultSink,
    SearcherSpec,
    SearchFn,
    SearchHit,
    SinkReport,
    builtin_searchers,
    dedupe_hits,
    get_searcher,
    load_providers,
    parallel_search,
    registry_search,
    search_brave,
    search_bright_data,
    search_ddg,
    search_google_search,
    search_tavily,
    searcher_ids,
)

__all__ = [
    "CrawlerName",
    "CrawlSpec",
    "DorkError",
    "ExtractorName",
    "NullSink",
    "PrefilterPolicy",
    "ProvidersConfig",
    "ResultSink",
    "SearchFn",
    "SearchHit",
    "SearcherSpec",
    "SinkReport",
    "any_of",
    "builtin_searchers",
    "dedupe_hits",
    "dork",
    "get_searcher",
    "load_providers",
    "near_dedupe",
    "normalize_hit",
    "parallel_search",
    "prefilter_hits",
    "registry_search",
    "search_bright_data",
    "search_brave",
    "search_ddg",
    "search_google_search",
    "searcher_ids",
    "search_tavily",
]
