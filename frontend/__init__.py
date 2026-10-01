"""Frontend package: provider registry, searchers and dork builder."""

from __future__ import annotations

from WebSearch.frontend.apis import builtin_searchers
from WebSearch.frontend.dorks import DorkError, any_of, dork
from WebSearch.frontend.models import SearchFn, SearchHit, dedupe_hits
from WebSearch.frontend.providers import (
    CrawlSpec,
    ProvidersConfig,
    SearcherSpec,
    get_searcher,
    load_providers,
)
from WebSearch.frontend.websearchers import parallel_search, registry_search, searcher_ids

__all__ = [
    "CrawlSpec",
    "DorkError",
    "ProvidersConfig",
    "SearchFn",
    "SearchHit",
    "SearcherSpec",
    "any_of",
    "builtin_searchers",
    "dedupe_hits",
    "dork",
    "get_searcher",
    "load_providers",
    "parallel_search",
    "registry_search",
    "searcher_ids",
]
