"""Frontend package: provider registry, searchers and dork builder."""

from __future__ import annotations

from WebSearch.frontend.apis import (
    builtin_searchers,
    search_brave,
    search_google_ground,
    search_tavily,
)
from WebSearch.frontend.dorks import DorkError, any_of, dork
from WebSearch.frontend.hits import near_dedupe, normalize_hit
from WebSearch.frontend.models import (
    NullSink,
    ResultSink,
    SearchFn,
    SearchHit,
    SinkReport,
    dedupe_hits,
)
from WebSearch.frontend.prefilter import prefilter_hits
from WebSearch.frontend.providers import (
    CrawlerName,
    CrawlSpec,
    ExtractorName,
    PrefilterPolicy,
    ProvidersConfig,
    SearcherSpec,
    get_searcher,
    load_providers,
)
from WebSearch.frontend.websearchers import (
    parallel_search,
    registry_search,
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
    "search_brave",
    "search_google_ground",
    "searcher_ids",
    "search_tavily",
]

