"""Registry, search types, HTTP plumbing, APIs, and parallel fan-out over ``providers.yaml``.

This module is a re-export facade. The implementation lives in focused sibling
modules; import from here (or from the submodules directly) — both work.

Layout:
    types.py      — dataclasses and protocols
    registry.py   — YAML/JSON providers file loading
    secrets.py    — Keychain and environment key resolution
    http_utils.py — shared HTTP client, executor, JSON requests
    cache.py      — process-local LRU and optional Redis result caching
    providers.py  — per-provider search implementations
    fanout.py     — parallel fan-out, RRF fusion, search entry points
"""

from __future__ import annotations

# --- cache ---
from WebSearch.frontend.cache import (
    cached_provider_search as _cached_provider_search,
)

# --- fan-out / fusion ---
from WebSearch.frontend.fanout import (
    _rrf_fuse,
    _select_specs,
    builtin_searchers,
    dedupe_hits,
    parallel_search,
    registry_search,
    search,
    searcher_ids,
    type_is_hit,
)

# --- HTTP utilities ---
from WebSearch.frontend.http_utils import (
    call_json,
    dig,
    request_json,
    shared_executor,
    shared_http_client,
)

# --- provider implementations ---
from WebSearch.frontend.providers import (
    hits_from_maps,
    search_apify,
    search_brave,
    search_bright_data,
    search_context,
    search_ddg,
    search_ddg_lite,
    search_ddg_mcp,
    search_exa,
    search_google_ground,
    search_google_search,
    search_jina,
    search_kimi,
    search_openrouter_web,
    search_parallel,
    search_tavily,
)

# --- registry (YAML loading) ---
from WebSearch.frontend.registry import (
    DEFAULT_AUTONOMOUS_DECISION,
    DEFAULT_AUTONOMOUS_DEDUPE,
    DEFAULT_AUTONOMOUS_MEMORY,
    DEFAULT_AUTONOMOUS_PLAYWRIGHT,
    DEFAULT_AUTONOMOUS_SUMMARIZE,
    SEARCHER_ALIASES,
    canon_searcher_id,
    get_searcher,
    load_providers,
    providers_config_path,
    providers_yaml_path,
    type_is_searcher_kind,
)

# --- secrets (keychain / env resolution) ---
from WebSearch.frontend.secrets import (
    env_base,
    env_key,
    env_keys,
)

# --- types (dataclasses and protocols) ---
from WebSearch.frontend.types import (
    _CRAWLERS,
    _EXTRACTORS,
    CrawlerName,
    CrawlSpec,
    ExtractorName,
    LlmSpec,
    NullSink,
    PrefilterPolicy,
    ProvidersConfig,
    ResultSink,
    SearcherKind,
    SearcherSpec,
    SearcherStatus,
    SearcherStatusName,
    SearchFn,
    SearchHit,
    SearchResult,
    SinkReport,
    WebSearcher,
)

# Internal names preserved for backward compatibility.
_httpx_json = call_json
_SEARCH_CACHE_TTL_S = 300.0
_MAX_WORKERS = 8

__all__ = [
    # Backward-compatible facade: names the refactor moved to providers/fanout/cache/types.
    "_CRAWLERS",
    "_EXTRACTORS",
    "_select_specs",
    "_cached_provider_search",
    "search_google_ground",
    "search_parallel",
    "CrawlerName",
    "CrawlSpec",
    "DEFAULT_AUTONOMOUS_DECISION",
    "DEFAULT_AUTONOMOUS_DEDUPE",
    "DEFAULT_AUTONOMOUS_MEMORY",
    "DEFAULT_AUTONOMOUS_PLAYWRIGHT",
    "DEFAULT_AUTONOMOUS_SUMMARIZE",
    "LlmSpec",
    "ExtractorName",
    "NullSink",
    "PrefilterPolicy",
    "ProvidersConfig",
    "ResultSink",
    "SearchFn",
    "SearchHit",
    "SearchResult",
    "SearcherKind",
    "SearcherSpec",
    "SearcherStatus",
    "SearcherStatusName",
    "SinkReport",
    "search",
    "WebSearcher",
    "_httpx_json",
    "_rrf_fuse",
    "builtin_searchers",
    "call_json",
    "dedupe_hits",
    "dig",
    "env_base",
    "env_key",
    "env_keys",
    "get_searcher",
    "hits_from_maps",
    "load_providers",
    "parallel_search",
    "providers_config_path",
    "providers_yaml_path",
    "shared_executor",
    "shared_http_client",
    "registry_search",
    "request_json",
    "search_apify",
    "search_bright_data",
    "search_brave",
    "search_ddg",
    "search_ddg_lite",
    "search_exa",
    "search_openrouter_web",
    "SEARCHER_ALIASES",
    "canon_searcher_id",
    "search_google_search",
    "search_tavily",
    "search_jina",
    "search_kimi",
    "search_context",
    "search_ddg_mcp",
    "searcher_ids",
    "type_is_hit",
    "type_is_searcher_kind",
]
