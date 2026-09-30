"""Frontend package: provider registry and websearcher contract."""

from __future__ import annotations

from WebSearch.frontend.apis import builtin_searchers
from WebSearch.frontend.providers import (
    CrawlSpec,
    ProvidersConfig,
    SearcherSpec,
    get_searcher,
    load_providers,
)
from WebSearch.frontend.websearchers import SearchHit, registry_search, searcher_ids

__all__ = [
    "CrawlSpec",
    "ProvidersConfig",
    "SearchHit",
    "SearcherSpec",
    "builtin_searchers",
    "get_searcher",
    "load_providers",
    "registry_search",
    "searcher_ids",
]
