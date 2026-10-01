"""Registry, search types, HTTP plumbing, APIs, and parallel fan-out over ``providers.yaml``."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal, Protocol

import yaml

from WebSearch.repeater import normalize_url, repeater

logger = logging.getLogger(__name__)

_MAX_WORKERS = 8
_APIFY_ACTOR = "apify~google-search-scraper"

# --- providers.yaml registry -------------------------------------------------

SearcherKind = Literal["docs", "websearcher"]
ExtractorName = Literal["selectolax", "selectolax_regex", "regex", "trafilatura", "bs4"]
CrawlerName = Literal["httpx", "scrapy", "playwright", "crawlee"]

_EXTRACTORS: tuple[ExtractorName, ...] = (
    "selectolax",
    "selectolax_regex",
    "regex",
    "trafilatura",
    "bs4",
)
_CRAWLERS: tuple[CrawlerName, ...] = ("httpx", "scrapy", "playwright", "crawlee")


@dataclass(frozen=True, slots=True)
class SearcherSpec:
    """One ``searchers:`` entry of ``providers.yaml``."""

    id: str
    kind: SearcherKind
    api_key_env: str | None = None
    engine: str | None = None
    description: str = ""
    base_url: str | None = None
    base_url_env: str | None = None


@dataclass(frozen=True, slots=True)
class CrawlSpec:
    """The ``crawl:`` block: limits and crawler order for fetching hit URLs."""

    timeout_s: float = 20.0
    max_bytes: int = 1_048_576
    max_urls: int = 8
    schemes: tuple[str, ...] = ("http", "https")
    crawler_order: tuple[CrawlerName, ...] = _CRAWLERS


@dataclass(frozen=True, slots=True)
class PrefilterPolicy:
    """The ``prefilter:`` block: which hits are dropped before fusion."""

    schemes: tuple[str, ...] = ("http", "https")
    blocked_domains: tuple[str, ...] = ()
    min_snippet_chars: int = 0
    require_title: bool = True


@dataclass(frozen=True, slots=True)
class ProvidersConfig:
    """Parsed ``providers.yaml``."""

    version: int
    searchers: tuple[SearcherSpec, ...]
    extractor_order: tuple[ExtractorName, ...]
    crawl: CrawlSpec = field(default_factory=CrawlSpec)
    prefilter: PrefilterPolicy = field(default_factory=PrefilterPolicy)


# --- search result types -----------------------------------------------------

#: Search implementation signature: ``(query, spec) -> hits``.
SearchFn = Callable[[str, SearcherSpec], Sequence["SearchHit"]]


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One search result from one searcher."""

    title: str
    url: str
    snippet: str
    searcher_id: str
    #: Tokens the search API reported for the call; set on the first hit only.
    api_tokens: int = 0
    #: Searcher ids whose near-duplicate hit was merged into this one.
    also_from: tuple[str, ...] = ()


class WebSearcher(Protocol):
    """A searcher bound to its registry spec."""

    spec: SearcherSpec

    def search(self, query: str) -> Sequence[SearchHit]: ...


@dataclass(frozen=True, slots=True)
class SinkReport:
    """Outcome of one :meth:`ResultSink.store` call.

    ``detail`` is free text the sink may use to say how it ran; WebSearch never
    interprets it.
    """

    stored: int
    skipped: int = 0
    detail: str = ""


class ResultSink(Protocol):
    """Receives the final, cleaned hits (for example to index them)."""

    def store(self, hits: Sequence[SearchHit]) -> SinkReport: ...


class NullSink:
    """Sink that stores nothing."""

    def store(self, hits: Sequence[SearchHit]) -> SinkReport:
        """Return a zero-count report without persisting hits."""
        return SinkReport(stored=0)


def type_is_hit(value: object) -> bool:
    """Return whether *value* is a ``SearchHit``.

    Args:
        value (object): Candidate object.

    Returns:
        bool: True if ``SearchHit``.
    """
    return isinstance(value, SearchHit)


def dedupe_hits(hits: Sequence[SearchHit]) -> list[SearchHit]:
    """Drop hits whose canonical URL was already seen; first occurrence wins.

    Args:
        hits (Sequence[SearchHit]): Hits in priority order.

    Returns:
        list[SearchHit]: Unique hits, order preserved.
    """
    seen: set[str] = set()
    unique: list[SearchHit] = []
    for hit in hits:
        key = normalize_url(hit.url)
        if key in seen:
            continue
        seen.add(key)
        unique.append(hit)
    return unique


def providers_yaml_path() -> Path:
    """Return the path to the packaged ``providers.yaml``.

    Returns:
        Path: Absolute path next to the ``WebSearch`` package.
    """
    return Path(__file__).resolve().parents[1] / "providers.yaml"


def type_is_searcher_kind(value: object) -> bool:
    """Return whether *value* is a known ``SearcherKind``.

    Args:
        value (object): Raw YAML kind.

    Returns:
        bool: True for ``docs`` or ``websearcher``.
    """
    return value in ("docs", "websearcher")


def load_providers(path: Path | None = None) -> ProvidersConfig:
    """Parse ``providers.yaml``.

    Args:
        path (Path | None): Override path; default is :func:`providers_yaml_path`.

    Returns:
        ProvidersConfig: Searchers, extractor order, crawl/crawler settings.

    Raises:
        ValueError: If YAML is not a mapping, names an unknown extractor/crawler,
            or has a non-numeric ``version``/``crawl`` limit.
    """
    raw = yaml.safe_load((path or providers_yaml_path()).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("providers.yaml must be a mapping")
    searchers: list[SearcherSpec] = []
    for item in raw.get("searchers") or []:
        if not isinstance(item, dict):
            continue
        kind_raw = item.get("kind", "websearcher")
        if kind_raw == "docs":
            kind: SearcherKind = "docs"
        elif kind_raw == "websearcher":
            kind = "websearcher"
        else:
            raise ValueError(f"unknown searcher kind: {kind_raw!r}")
        env = item.get("api_key_env")
        base = item.get("base_url")
        base_env = item.get("base_url_env")
        searchers.append(
            SearcherSpec(
                id=str(item["id"]),
                kind=kind,
                api_key_env=str(env) if isinstance(env, str) else None,
                engine=(
                    str(item["engine"]) if isinstance(item.get("engine"), str) else None
                ),
                description=str(item.get("description") or ""),
                base_url=str(base) if isinstance(base, str) else None,
                base_url_env=str(base_env) if isinstance(base_env, str) else None,
            )
        )
    extractors_block = raw.get("extractors")
    order_raw = (
        extractors_block.get("order") if isinstance(extractors_block, dict) else None
    ) or list(_EXTRACTORS)
    order = _parse_names(order_raw, _EXTRACTORS, "extractor")
    crawlers_block = raw.get("crawlers")
    crawler_raw = (
        crawlers_block.get("order") if isinstance(crawlers_block, dict) else None
    ) or list(_CRAWLERS)
    crawler_order = _parse_names(crawler_raw, _CRAWLERS, "crawler")
    crawl_block = raw.get("crawl")
    crawl_raw: dict[str, object] = crawl_block if isinstance(crawl_block, dict) else {}
    schemes_val = crawl_raw.get("schemes")
    if isinstance(schemes_val, list):
        schemes = tuple(str(s) for s in schemes_val) or ("http", "https")
    else:
        schemes = ("http", "https")
    prefilter_block = raw.get("prefilter")
    prefilter_raw: dict[str, object] = (
        prefilter_block if isinstance(prefilter_block, dict) else {}
    )
    return ProvidersConfig(
        version=_coerce_number(raw.get("version"), int, 1, "version"),
        searchers=tuple(searchers),
        extractor_order=order,
        crawl=CrawlSpec(
            timeout_s=_coerce_number(
                crawl_raw.get("timeout_s"), float, 20.0, "crawl.timeout_s"
            ),
            max_bytes=_coerce_number(
                crawl_raw.get("max_bytes"), int, 1_048_576, "crawl.max_bytes"
            ),
            max_urls=_coerce_number(
                crawl_raw.get("max_urls"), int, 8, "crawl.max_urls"
            ),
            schemes=schemes,
            crawler_order=crawler_order,
        ),
        prefilter=_parse_prefilter(prefilter_raw),
    )


def _str_tuple(value: object) -> tuple[str, ...]:
    """Lowercased, stripped, non-empty strings of a yaml list; anything else → ``()``."""
    if not isinstance(value, list):
        return ()
    return tuple(
        text for item in value if (text := str(item).strip().lower().lstrip("."))
    )


def _parse_prefilter(raw: dict[str, object]) -> PrefilterPolicy:
    """Build a :class:`PrefilterPolicy` from the ``prefilter:`` yaml block."""
    require_title = raw.get("require_title")
    if require_title is None:
        require_title = True
    elif not isinstance(require_title, bool):
        raise ValueError(
            f"providers.yaml: prefilter.require_title must be true or false, got {require_title!r}"
        )
    return PrefilterPolicy(
        schemes=_str_tuple(raw.get("schemes")) or ("http", "https"),
        blocked_domains=_str_tuple(raw.get("blocked_domains")),
        min_snippet_chars=_coerce_number(
            raw.get("min_snippet_chars"), int, 0, "prefilter.min_snippet_chars"
        ),
        require_title=require_title,
    )


def _coerce_number[N: (int, float)](
    value: object, cast: Callable[[Any], N], default: N, label: str
) -> N:
    """Cast a yaml scalar with *cast*; ``None``/wrong shape → *default*.

    Raises:
        ValueError: If a string/number cannot be converted (names *label*).
    """
    if (
        value is None
        or isinstance(value, bool)
        or not isinstance(value, int | float | str)
    ):
        return default
    try:
        return cast(value)
    except ValueError as exc:
        raise ValueError(
            f"providers.yaml: {label} must be a number, got {value!r}"
        ) from exc


def _parse_names[T: str](
    raw: object, allowed: tuple[T, ...], label: str
) -> tuple[T, ...]:
    """Validate a yaml ``order`` list against *allowed*; empty/invalid shape → all."""
    if not isinstance(raw, list):
        return allowed
    order: list[T] = []
    for name in raw:
        match = next((a for a in allowed if a == name), None)
        if match is None:
            raise ValueError(f"unknown {label}: {name!r}")
        order.append(match)
    return tuple(order) or allowed


def get_searcher(config: ProvidersConfig, searcher_id: str) -> SearcherSpec:
    """Look up a searcher by id.

    Args:
        config (ProvidersConfig): Loaded registry.
        searcher_id (str): ``searchers[].id`` in YAML.

    Returns:
        SearcherSpec: Matching spec.

    Raises:
        KeyError: If *searcher_id* is absent.
    """
    for spec in config.searchers:
        if spec.id == searcher_id:
            return spec
    raise KeyError(searcher_id)


# --- HTTP / JSON plumbing (fail closed) ----------------------------------------


def env_key(spec: SearcherSpec) -> str:
    """Read an API key from the environment using the spec's env var name.

    Args:
        spec: Searcher configuration from ``providers.yaml``.

    Returns:
        str: The trimmed key, or an empty string if the env var is unset.
    """
    name = spec.api_key_env
    if not name:
        return ""
    return os.environ.get(name, "").strip()


def env_base(spec: SearcherSpec) -> str:
    """Resolve the searcher base URL from env var or spec field.

    Args:
        spec: Searcher configuration from ``providers.yaml``.

    Returns:
        str: Root URL with trailing slashes removed, or an empty string.
    """
    if spec.base_url_env:
        return os.environ.get(spec.base_url_env, "").strip().rstrip("/")
    return (spec.base_url or "").rstrip("/")


@repeater.s
def request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    params: dict[str, str] | None = None,
    timeout_s: float = 20.0,
) -> Any:
    """GET/POST JSON. Deferred httpx import.

    Args:
        method (str): ``GET`` or ``POST``.
        url (str): Absolute URL.
        headers (dict[str, str] | None): Extra headers.
        json_body (dict[str, Any] | None): POST body.
        params (dict[str, str] | None): Query string.
        timeout_s (float): Request timeout in seconds.

    Returns:
        Any: Parsed JSON.

    Raises:
        TimeoutError, OSError, ConnectionError: After retries.
    """
    try:
        import httpx
    except ImportError as exc:
        raise OSError("httpx not installed") from exc

    try:
        response = httpx.request(
            method,
            url,
            headers=headers,
            json=json_body,
            params=params,
            timeout=timeout_s,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise OSError(str(exc)) from exc


def call_json(method: str, url: str, **kwargs: Any) -> Any | None:
    """Fail-closed wrapper over :func:`request_json`.

    Returns:
        Any | None: Parsed JSON, or ``None`` on a transient network failure or a
        body that is not valid JSON. Other errors propagate.
    """
    try:
        return request_json(method, url, **kwargs)
    except (
        TimeoutError,
        OSError,
        ConnectionError,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ):
        return None


_httpx_json = call_json


def dig(data: Any, *path: str) -> object:
    """Walk nested dicts along *path*; ``None`` if any step is not a dict."""
    node: object = data
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def hits_from_maps(
    rows: object,
    searcher_id: str,
    *,
    title: str,
    url: str,
    snippet: str,
) -> list[SearchHit]:
    """Normalize a list of raw result dicts into ``SearchHit`` objects.

    Rows without an ``http``/``https`` URL are skipped so downstream callers
    never have to validate schemes themselves.

    Args:
        rows: Raw result list from a search API response.
        searcher_id: Identifier of the searcher that produced the rows.
        title: Key in each row dict that holds the result title.
        url: Key in each row dict that holds the result URL.
        snippet: Key in each row dict that holds the result snippet.

    Returns:
        list[SearchHit]: Valid, normalized hits.
    """
    if not isinstance(rows, list):
        return []
    hits: list[SearchHit] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        href = str(row.get(url) or "")
        if not href.startswith("http"):
            continue
        hits.append(
            SearchHit(
                title=str(row.get(title) or href),
                url=href,
                snippet=str(row.get(snippet) or ""),
                searcher_id=searcher_id,
            )
        )
    return hits


# --- HTTP search APIs (fail closed) --------------------------------------------


def search_brave(query: str, spec: SearcherSpec) -> list[SearchHit]:
    """Brave Search API.

    Args:
        query (str): User query.
        spec (SearcherSpec): Needs ``BRAVE_API_KEY`` via ``api_key_env``.

    Returns:
        list[SearchHit]: Web results, or ``[]`` if the key is missing or the call fails.
    """
    token = env_key(spec)
    if not token:
        return []
    data = _httpx_json(
        "GET",
        "https://api.search.brave.com/res/v1/web/search",
        headers={"Accept": "application/json", "X-Subscription-Token": token},
        params={"q": query},
    )
    if data is None:
        return []
    return hits_from_maps(
        dig(data, "web", "results"), spec.id, title="title", url="url", snippet="description"
    )


def search_tavily(query: str, spec: SearcherSpec) -> list[SearchHit]:
    """Tavily Search API.

    Args:
        query (str): User query.
        spec (SearcherSpec): Needs ``TAVILY_API_KEY``.

    Returns:
        list[SearchHit]: Results, or ``[]`` on missing key / failure.
    """
    token = env_key(spec)
    if not token:
        return []
    data = _httpx_json(
        "POST",
        "https://api.tavily.com/search",
        json_body={"api_key": token, "query": query, "max_results": 8},
    )
    if data is None:
        return []
    return hits_from_maps(
        dig(data, "results"), spec.id, title="title", url="url", snippet="content"
    )


def search_apify(query: str, spec: SearcherSpec) -> list[SearchHit]:
    """Google SERP through the Apify ``google-search-scraper`` actor (sync run).

    Args:
        query (str): User query (dork strings work as-is).
        spec (SearcherSpec): ``base_url`` plus ``APIFY_TOKEN``.

    Returns:
        list[SearchHit]: Organic results, or ``[]`` without a token or on failure.
    """
    token = env_key(spec)
    if not token:
        return []
    root = env_base(spec) or "https://api.apify.com/v2"
    data = _httpx_json(
        "POST",
        f"{root}/acts/{_APIFY_ACTOR}/run-sync-get-dataset-items",
        headers={"Authorization": f"Bearer {token}"},
        json_body={"queries": query, "maxPagesPerQuery": 1, "resultsPerPage": 10},
        timeout_s=120.0,
    )
    if not isinstance(data, list):
        return []
    hits: list[SearchHit] = []
    for page in data:
        organic = dig(page, "organicResults")
        hits.extend(
            hits_from_maps(organic, spec.id, title="title", url="url", snippet="description")
        )
    return hits


def search_exa(query: str, spec: SearcherSpec) -> list[SearchHit]:
    """Exa Search API.

    Args:
        query (str): User query.
        spec (SearcherSpec): Needs ``EXA_API_KEY``.

    Returns:
        list[SearchHit]: Results, or ``[]`` on missing key / failure.
    """
    token = env_key(spec)
    if not token:
        return []
    data = _httpx_json(
        "POST",
        "https://api.exa.ai/search",
        headers={"x-api-key": token, "Content-Type": "application/json"},
        json_body={"query": query, "numResults": 8},
    )
    if data is None:
        return []
    return hits_from_maps(dig(data, "results"), spec.id, title="title", url="url", snippet="text")


def search_searxng(query: str, spec: SearcherSpec) -> list[SearchHit]:
    """SearXNG JSON search with DuckDuckGo + Bing engines.

    Args:
        query (str): User query.
        spec (SearcherSpec): ``base_url_env`` (``SEARXNG_URL``) and ``engine``.

    Returns:
        list[SearchHit]: Results, or ``[]`` if the instance URL is unset or the call fails.
    """
    root = env_base(spec)
    if not root:
        return []
    engines = spec.engine or "duckduckgo,bing"
    data = _httpx_json(
        "GET",
        f"{root}/search",
        params={"q": query, "format": "json", "engines": engines},
    )
    if data is None:
        return []
    return hits_from_maps(
        dig(data, "results"), spec.id, title="title", url="url", snippet="content"
    )


def search_google_ground(query: str, spec: SearcherSpec) -> list[SearchHit]:
    """Gemini with Google Search grounding; returns the cited web sources.

    ``spec.engine`` is the model id, ``spec.base_url`` the API root, and the key
    comes from ``GEMINI_API_KEY``. Cited URIs are Google redirect links; the
    midend follows redirects when scraping.

    Args:
        query (str): User query (dork strings work as-is).
        spec (SearcherSpec): Searcher configuration.

    Returns:
        list[SearchHit]: One hit per grounding chunk. The API-reported token total
        is stored on the first hit. ``[]`` without a key or on failure.
    """
    token = env_key(spec)
    if not token:
        return []
    root = env_base(spec) or "https://generativelanguage.googleapis.com/v1beta"
    model = spec.engine or "gemini-2.5-flash"
    data = _httpx_json(
        "POST",
        f"{root}/models/{model}:generateContent",
        headers={"x-goog-api-key": token, "Content-Type": "application/json"},
        json_body={
            "contents": [{"parts": [{"text": query}]}],
            "tools": [{"google_search": {}}],
        },
        timeout_s=60.0,
    )
    candidates = dig(data, "candidates")
    if not isinstance(candidates, list) or not candidates:
        return []
    meta = dig(candidates[0], "groundingMetadata")
    chunks = dig(meta, "groundingChunks")
    if not isinstance(chunks, list):
        return []
    quoted: dict[int, list[str]] = {}
    supports = dig(meta, "groundingSupports")
    for support in supports if isinstance(supports, list) else []:
        text = dig(support, "segment", "text")
        idxs = dig(support, "groundingChunkIndices")
        if isinstance(text, str) and isinstance(idxs, list):
            for i in idxs:
                if isinstance(i, int):
                    quoted.setdefault(i, []).append(text)
    rows = [
        {**web, "snippet": " ".join(quoted.get(i, []))}
        for i, chunk in enumerate(chunks)
        if isinstance(web := dig(chunk, "web"), dict)
    ]
    hits = hits_from_maps(rows, spec.id, title="title", url="uri", snippet="snippet")
    total = dig(data, "usageMetadata", "totalTokenCount")
    if hits and isinstance(total, int):
        hits[0] = replace(hits[0], api_tokens=total)
    return hits


def search_ddg(query: str, spec: SearcherSpec) -> list[SearchHit]:
    """DuckDuckGo text search via ``duckduckgo-search``.

    Args:
        query (str): User query.
        spec (SearcherSpec): Registry entry (no API key needed).

    Returns:
        list[SearchHit]: Results, or ``[]`` if the package is missing or the call fails.
    """
    del spec
    try:
        from duckduckgo_search import DDGS
    except ImportError as exc:
        raise OSError("duckduckgo-search not installed") from exc

    try:
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=10)
    except Exception as exc:
        raise OSError(str(exc)) from exc
    return [
        SearchHit(
            title=str(item.get("title") or item.get("href") or ""),
            url=str(item["href"]),
            snippet=str(item.get("body") or ""),
            searcher_id="ddg",
        )
        for item in results
        if isinstance(item, dict) and str(item.get("href", "")).startswith("http")
    ]


def builtin_searchers() -> dict[str, SearchFn]:
    """Named HTTP searchers from ``providers.yaml`` ids.

    Returns:
        dict[str, SearchFn]: brave, ddg, tavily, apify, exa, searxng.
    """
    return {
        "brave": search_brave,
        "ddg": search_ddg,
        "tavily": search_tavily,
        "apify": search_apify,
        "exa": search_exa,
        "google_ground": search_google_ground,
        "searxng": search_searxng,
    }


# --- fan-out / fusion ----------------------------------------------------------


def searcher_ids(config: ProvidersConfig | None = None) -> tuple[str, ...]:
    """List searcher ids from config order.

    Args:
        config (ProvidersConfig | None): Loaded YAML; default from disk.

    Returns:
        tuple[str, ...]: ``searchers[].id`` values.
    """
    cfg = config or load_providers()
    return tuple(spec.id for spec in cfg.searchers)


def registry_search(
    query: str,
    *,
    config: ProvidersConfig | None = None,
    backends: Mapping[str, SearchFn] | None = None,
    searcher_id: str | None = None,
) -> list[SearchHit]:
    """Run ``query`` on YAML searchers until one returns hits.

    Args:
        query (str): User query.
        config (ProvidersConfig | None): Registry; default ``load_providers()``.
        backends (Mapping[str, SearchFn] | None): id → callable. Default HTTP APIs.
        searcher_id (str | None): Restrict to one id.

    Returns:
        list[SearchHit]: First non-empty result list (failover on empty).

    Raises:
        KeyError: If ``searcher_id`` is not in the registry.
    """
    from WebSearch.backend.prefilter import prefilter_hits

    cfg = config or load_providers()
    table = dict(backends if backends is not None else builtin_searchers())
    hits: list[SearchHit] = []
    for spec in _select_specs(cfg, searcher_id):
        fn = table.get(spec.id)
        if fn is None:
            continue
        hits.extend(prefilter_hits(fn(query, spec), cfg.prefilter)[0])
        if hits:
            break
    return hits


def _select_specs(
    config: ProvidersConfig, searcher_id: str | None
) -> list[SearcherSpec]:
    specs = list(config.searchers)
    if searcher_id is None:
        return specs
    specs = [s for s in specs if s.id == searcher_id]
    if not specs:
        raise KeyError(searcher_id)
    return specs


def _rrf_fuse(
    batches: Sequence[Sequence[SearchHit]], *, k: int = 60
) -> list[SearchHit]:
    """Reciprocal-rank fusion across per-provider rankings.

    A URL returned by several providers outranks one returned by a single
    provider, so consensus sources lead the merged list. Ties keep first-seen
    (YAML) order, so the merge stays deterministic.

    Args:
        batches (Sequence[Sequence[SearchHit]]): One ranked batch per searcher.
        k (int): RRF constant; larger flattens provider rank differences.

    Returns:
        list[SearchHit]: Fused hits (still containing per-URL duplicates).
    """
    score: dict[str, float] = {}
    order: list[str] = []
    keep: dict[str, SearchHit] = {}
    for batch in batches:
        for rank, hit in enumerate(batch):
            key = normalize_url(hit.url)
            score[key] = score.get(key, 0.0) + 1.0 / (k + rank + 1)
            if key not in keep:
                keep[key] = hit
                order.append(key)
    order.sort(key=lambda key: score[key], reverse=True)
    return [keep[key] for key in order]


def parallel_search(
    query: str,
    *,
    config: ProvidersConfig | None = None,
    backends: Mapping[str, SearchFn] | None = None,
    searcher_id: str | None = None,
    max_workers: int = _MAX_WORKERS,
    timeout_s: float = 30.0,
    limit: int = 0,
    fuse: bool = True,
    near_distance: int | None = 6,
    sink: ResultSink | None = None,
) -> list[SearchHit]:
    """Send one ``query`` to every configured searcher at once and merge the hits.

    Searchers without a backend are skipped. A searcher that raises a transient
    error contributes no hits and does not affect the others. If the overall
    ``timeout_s`` budget expires, unfinished searchers are abandoned and the
    finished batches still answer. Merged hits are consensus-ranked (RRF across
    per-provider rankings) unless ``fuse=False`` keeps plain YAML order.

    Each provider's batch is prefiltered first (``config.prefilter``) so junk
    cannot gain rank from consensus. After fusion the hits are deduplicated by
    canonical URL, normalized, near-deduplicated, capped to ``limit`` (0 = no
    cap) and handed to ``sink``. A sink that raises ``OSError`` is logged and
    the hits are still returned. When every hit is rejected the result is empty
    and the API token total is not reported.

    Args:
        query (str): User query (a dork string works as-is).
        config (ProvidersConfig | None): Registry; default ``load_providers()``.
        backends (Mapping[str, SearchFn] | None): id → callable. Default HTTP APIs.
        searcher_id (str | None): Restrict to one id.
        max_workers (int): Thread cap; values below 1 are clamped to 1.
        timeout_s (float): Overall wall-clock budget for all searchers;
            ``<= 0`` waits unboundedly (each HTTP call still has its own timeout).
        limit (int): Max merged hits; ``0`` returns everything.
        fuse (bool): RRF consensus ranking across providers (default) instead
            of raw YAML-order concatenation.
        near_distance (int | None): Largest SimHash Hamming distance counted
            as a near-duplicate; ``None`` disables near-dedupe.
        sink (ResultSink | None): Receives the final hits when there are any.

    Returns:
        list[SearchHit]: Unique hits from all searchers, best first.

    Raises:
        KeyError: If ``searcher_id`` is not in the registry.
    """
    from WebSearch.backend.prefilter import prefilter_hits
    from WebSearch.frontend.hits import near_dedupe, normalize_hit

    cfg = config or load_providers()
    table = dict(backends if backends is not None else builtin_searchers())
    jobs = [
        (spec, table[spec.id])
        for spec in _select_specs(cfg, searcher_id)
        if spec.id in table
    ]
    if not jobs:
        return []

    def run(job: tuple[SearcherSpec, SearchFn]) -> Sequence[SearchHit]:
        spec, fn = job
        try:
            return fn(query, spec)
        except TimeoutError, OSError, ConnectionError, ValueError:
            logger.warning("searcher %s failed", spec.id, exc_info=True)
            return []

    executor = ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(jobs))))
    wait = timeout_s if timeout_s and timeout_s > 0 else None
    pending = [(index, executor.submit(run, job)) for index, job in enumerate(jobs)]
    by_index: dict[int, Sequence[SearchHit]] = {}
    try:
        for future in as_completed([future for _, future in pending], timeout=wait):
            try:
                index = next(i for i, f in pending if f is future)
                by_index[index] = future.result()
            except Exception:
                logger.warning("searcher crashed", exc_info=True)
    except TimeoutError:
        for _, future in pending:
            future.cancel()
        logger.warning(
            "search budget %ss exceeded; abandoning slow searchers", timeout_s
        )
    finally:
        executor.shutdown(wait=False)
    batches = [by_index[index] for index in sorted(by_index)]
    api_tokens = sum(hit.api_tokens for batch in batches for hit in batch)
    clean = [prefilter_hits(batch, cfg.prefilter)[0] for batch in batches]
    merged = _rrf_fuse(clean) if fuse else [hit for batch in clean for hit in batch]
    hits = [normalize_hit(hit) for hit in dedupe_hits(merged)]
    if near_distance is not None:
        hits = near_dedupe(hits, max_distance=near_distance)
    if limit and limit > 0:
        hits = hits[:limit]
    if hits and api_tokens:
        hits = [replace(hit, api_tokens=0) for hit in hits]
        hits[0] = replace(hits[0], api_tokens=api_tokens)
    if sink is not None and hits:
        _store(sink, hits)
    return hits


def _store(sink: ResultSink, hits: Sequence[SearchHit]) -> None:
    """Hand *hits* to *sink*; a transient I/O failure never loses the search."""
    try:
        report = sink.store(hits)
    except OSError:
        logger.exception("result sink failed; returning hits unstored")
        return
    logger.debug(
        "sink stored=%d skipped=%d %s", report.stored, report.skipped, report.detail
    )


__all__ = [
    "CrawlerName",
    "CrawlSpec",
    "ExtractorName",
    "NullSink",
    "PrefilterPolicy",
    "ProvidersConfig",
    "ResultSink",
    "SearchFn",
    "SearchHit",
    "SearcherKind",
    "SearcherSpec",
    "SinkReport",
    "WebSearcher",
    "_httpx_json",
    "_rrf_fuse",
    "builtin_searchers",
    "call_json",
    "dedupe_hits",
    "dig",
    "env_base",
    "env_key",
    "get_searcher",
    "hits_from_maps",
    "load_providers",
    "parallel_search",
    "providers_yaml_path",
    "registry_search",
    "request_json",
    "search_apify",
    "search_brave",
    "search_ddg",
    "search_exa",
    "search_google_ground",
    "search_searxng",
    "search_tavily",
    "searcher_ids",
    "type_is_hit",
    "type_is_searcher_kind",
]
