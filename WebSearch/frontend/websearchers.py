"""Registry, search types, HTTP plumbing, APIs, and parallel fan-out over ``providers.yaml``."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol
from urllib.parse import urlencode, urlsplit

import yaml

from swarm_sdk.retrieval.redis_exact import RedisExactCache
from WebSearch.frontend.dorks import parse_dork
from WebSearch.repeater import normalize_url, repeater

if TYPE_CHECKING:
    from httpx import Client as HttpxClient

logger = logging.getLogger(__name__)

_MAX_WORKERS = 8
_APIFY_ACTOR = "apify~google-search-scraper"

# --- providers.yaml registry -------------------------------------------------

SearcherKind = Literal["docs", "websearcher"]
ExtractorName = Literal["selectolax", "selectolax_regex", "regex", "trafilatura", "bs4"]
CrawlerName = Literal[
    "httpx", "httpx2", "requests", "aiohttp", "curl_cffi", "scrapy", "playwright", "crawlee"
]

_EXTRACTORS: tuple[ExtractorName, ...] = (
    "selectolax",
    "selectolax_regex",
    "regex",
    "trafilatura",
    "bs4",
)
_CRAWLERS: tuple[CrawlerName, ...] = (
    "httpx",
    "httpx2",
    "requests",
    "aiohttp",
    "curl_cffi",
    "scrapy",
    "playwright",
    "crawlee",
)


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
    #: ``native`` sends the dork as typed; ``translate`` maps operators to API fields.
    dork: str = "native"
    #: Extra key env names tried in order when the primary key is missing, rejected (401/403)
    #: or out of quota (429). Only ``google_search`` rotates on failure today.
    api_key_fallback_envs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LlmSpec:
    """The ``llm:`` block: the chat model that drives the browser agent.

    Attributes:
        model: ``provider:name`` for ``load_chat_model`` (``WEBSEARCH_LLM_MODEL`` overrides).
        max_steps: Cap on agent graph steps (model and tool turns together).
        max_pages: Cap on pages the agent may open.
        max_chars: Text kept per opened page.
    """

    model: str = ""
    max_steps: int = 12
    max_pages: int = 4
    max_chars: int = 6000


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


#: First Keychain-ready non-Gemini name drives Playwright. A slotted dataclass
#: does not keep this tuple as a class attribute, so parsers read the constant.
DEFAULT_AUTONOMOUS_PLAYWRIGHT: tuple[str, ...] = (
    "openrouter:z-ai/glm-5.3-flash",
    "moonshot:kimi-k2.7-code",
    "zai:glm-5.2",
    "minimax:minimax-2.7-high-speed",
    "groq:openai/gpt-oss-120b",
    "cohere:command-a",
    "mistral:mistral-large-latest",
    "atlascloud:dots-studio/dots-3-note-prev-free",
    "poolside:poolside/laguna-s-2.1",
)
#: Gemini 3.5 Flash is preferred for semantic dedupe after deterministic
#: normalization; remaining names are fallbacks if its key is unavailable.
DEFAULT_AUTONOMOUS_DEDUPE: tuple[str, ...] = (
    "google:gemini-3.5-flash",
    "cohere:command-r7b",
    "groq:openai/gpt-oss-20b",
    "moonshot:kimi-k2.7-code-b",
    "xiaomi:mimo-v2.5-pro",
    "mistral:ministral-3-8b-latest",
    "sambanova:Meta-Llama-3.3-70B-Instruct",
    "fireworks:accounts/fireworks/models/kimi-k2.7",
)
#: Final answer synthesis over the normalized, deduplicated pages.
DEFAULT_AUTONOMOUS_SUMMARIZE: tuple[str, ...] = (
    "google:gemini-3.5-flash",
    "cohere:command-r7b",
    "groq:openai/gpt-oss-20b",
)
#: Memory provider. Mem0 stores and returns a brief for the same query.
DEFAULT_AUTONOMOUS_MEMORY: tuple[str, ...] = ("mem0",)
#: Decision maker. Jev Choice picks the Playwright model among ready names.
DEFAULT_AUTONOMOUS_DECISION: tuple[str, ...] = ("jev",)


@dataclass(frozen=True, slots=True)
class ProvidersConfig:
    """Parsed ``providers.yaml``."""

    version: int
    searchers: tuple[SearcherSpec, ...]
    extractor_order: tuple[ExtractorName, ...]
    crawl: CrawlSpec = field(default_factory=CrawlSpec)
    prefilter: PrefilterPolicy = field(default_factory=PrefilterPolicy)
    #: ``dork_presets:`` name → dork keyword arguments (``after_days`` allowed).
    dork_presets: dict[str, dict[str, Any]] = field(default_factory=dict)
    llm: LlmSpec = field(default_factory=LlmSpec)
    #: Vault-backed models that may drive Playwright. First ready name wins.
    autonomous_playwright: tuple[str, ...] = DEFAULT_AUTONOMOUS_PLAYWRIGHT
    #: A different model judges near-duplicates after blake2b. First ready name wins.
    autonomous_dedupe: tuple[str, ...] = DEFAULT_AUTONOMOUS_DEDUPE
    autonomous_summarize: tuple[str, ...] = DEFAULT_AUTONOMOUS_SUMMARIZE
    #: Memory provider names. The first ready name is Mem0.
    autonomous_memory: tuple[str, ...] = DEFAULT_AUTONOMOUS_MEMORY
    #: Decision maker names. The first ready name is Jev.
    autonomous_decision: tuple[str, ...] = DEFAULT_AUTONOMOUS_DECISION


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
    #: The query this hit was retrieved for; set by ``agent_tools.score_hits``.
    query: str = ""
    #: Lexical relevance of this hit to ``query`` in ``[0.0, 1.0]`` (0.0 = unscored).
    relevance: float = 0.0


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

    Resolves via ``importlib.resources`` so an installed wheel loads
    ``WebSearch/providers.yaml``, not a nested ``WebSearch/WebSearch/`` copy.

    Returns:
        Path: Absolute path of the package data file.
    """
    return Path(str(files("WebSearch").joinpath("providers.yaml")))


def providers_config_path() -> Path:
    """Resolve the providers file: ``WEBSEARCH_PROVIDERS``, else yaml, else json.

    Returns:
        Path: ``$WEBSEARCH_PROVIDERS`` if set, ``providers.yaml`` if it exists,
        otherwise ``providers.json`` next to the package.
    """
    override = os.environ.get("WEBSEARCH_PROVIDERS", "").strip()
    if override:
        return Path(override).expanduser()
    yaml_path = providers_yaml_path()
    json_path = yaml_path.with_suffix(".json")
    return json_path if (not yaml_path.exists() and json_path.exists()) else yaml_path


def _read_mapping(target: Path) -> object:
    """Parse a providers file by suffix: ``.json``/``.toml`` as structured, else YAML."""
    text = target.read_text(encoding="utf-8")
    suffix = target.suffix.lower()
    if suffix == ".json":
        try:
            return _json_loads(text)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"{target.name}: invalid JSON: {exc}") from exc
    if suffix == ".toml":
        import tomllib

        with target.open("rb") as fh:
            return tomllib.load(fh)
    return yaml.safe_load(text)


def type_is_searcher_kind(value: object) -> bool:
    """Return whether *value* is a known ``SearcherKind``.

    Args:
        value (object): Raw YAML kind.

    Returns:
        bool: True for ``docs`` or ``websearcher``.
    """
    return value in ("docs", "websearcher")


_PROVIDERS_CACHE: dict[tuple[str, int, int], ProvidersConfig] = {}


def load_providers(path: Path | None = None) -> ProvidersConfig:
    """Parse the providers file (YAML or JSON), cached per file version.

    Args:
        path (Path | None): Override path; default is :func:`providers_config_path`.

    Returns:
        ProvidersConfig: Searchers, extractor order, crawl/crawler settings.

    Raises:
        ValueError: If YAML is not a mapping, names an unknown extractor/crawler,
            or has a non-numeric ``version``/``crawl`` limit.
    """
    target = (path or providers_config_path()).resolve()
    stat = target.stat()
    key = (str(target), stat.st_mtime_ns, stat.st_size)
    cached = _PROVIDERS_CACHE.get(key)
    if cached is None:
        cached = _parse_providers(target)
        _PROVIDERS_CACHE[key] = cached
    return cached


def _parse_providers(target: Path) -> ProvidersConfig:
    """Parse the yaml file at *target* into a :class:`ProvidersConfig`."""
    raw = _read_mapping(target)
    if not isinstance(raw, dict):
        raise ValueError(f"{target.name} must be a mapping")
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
        fallbacks_raw = item.get("api_key_env_fallbacks")
        fallbacks = (
            tuple(str(name) for name in fallbacks_raw if isinstance(name, str))
            if isinstance(fallbacks_raw, list)
            else ()
        )
        dork_mode = str(item.get("dork") or "native")
        if dork_mode not in {"native", "translate"}:
            raise ValueError(f"searcher {item.get('id')!r}: dork must be native or translate")
        searchers.append(
            SearcherSpec(
                id=str(item["id"]),
                kind=kind,
                api_key_env=str(env) if isinstance(env, str) else None,
                engine=(str(item["engine"]) if isinstance(item.get("engine"), str) else None),
                description=str(item.get("description") or ""),
                base_url=str(base) if isinstance(base, str) else None,
                base_url_env=str(base_env) if isinstance(base_env, str) else None,
                dork=dork_mode,
                api_key_fallback_envs=fallbacks,
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
    prefilter_raw: dict[str, object] = prefilter_block if isinstance(prefilter_block, dict) else {}
    return ProvidersConfig(
        version=_coerce_number(raw.get("version"), int, 1, "version"),
        searchers=tuple(searchers),
        extractor_order=order,
        crawl=CrawlSpec(
            timeout_s=_coerce_number(crawl_raw.get("timeout_s"), float, 20.0, "crawl.timeout_s"),
            max_bytes=_coerce_number(crawl_raw.get("max_bytes"), int, 1_048_576, "crawl.max_bytes"),
            max_urls=_coerce_number(crawl_raw.get("max_urls"), int, 8, "crawl.max_urls"),
            schemes=schemes,
            crawler_order=crawler_order,
        ),
        prefilter=_parse_prefilter(prefilter_raw),
        dork_presets=_parse_presets(raw.get("dork_presets")),
        llm=_parse_llm(raw.get("llm")),
        autonomous_playwright=_parse_model_list(
            raw.get("autonomous"), "playwright", DEFAULT_AUTONOMOUS_PLAYWRIGHT
        ),
        autonomous_dedupe=_parse_model_list(
            raw.get("autonomous"), "dedupe", DEFAULT_AUTONOMOUS_DEDUPE
        ),
        autonomous_summarize=_parse_model_list(
            raw.get("autonomous"), "summarize", DEFAULT_AUTONOMOUS_SUMMARIZE
        ),
        autonomous_memory=_parse_model_list(
            raw.get("autonomous"), "memory", DEFAULT_AUTONOMOUS_MEMORY
        ),
        autonomous_decision=_parse_model_list(
            raw.get("autonomous"), "decision", DEFAULT_AUTONOMOUS_DECISION
        ),
    )


def _parse_presets(raw: object) -> dict[str, dict[str, Any]]:
    """``dork_presets:`` → ``{name: kwargs}``; non-mapping entries are rejected."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("dork_presets must be a mapping of name -> options")
    presets: dict[str, dict[str, Any]] = {}
    for name, options in raw.items():
        if not isinstance(options, dict):
            raise ValueError(f"dork_presets.{name} must be a mapping")
        presets[str(name)] = dict(options)
    return presets


def _parse_model_list(raw: object, role: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """``autonomous.<role>`` model names. A missing block keeps ``default``."""
    if raw is None:
        return default
    if not isinstance(raw, dict):
        raise ValueError("autonomous must be a mapping of role -> model names")
    if role not in raw:
        return default
    names = raw[role]
    if not isinstance(names, list):
        raise ValueError(f"autonomous.{role} must be a list of provider:name")
    return tuple(text for item in names if (text := str(item).strip()))


def _parse_llm(raw: object) -> LlmSpec:
    """``llm:`` block → :class:`LlmSpec`; ``WEBSEARCH_LLM_MODEL`` wins over ``model``."""
    block: dict[str, object] = raw if isinstance(raw, dict) else {}
    model = os.environ.get("WEBSEARCH_LLM_MODEL", "").strip() or str(block.get("model") or "")
    return LlmSpec(
        model=model,
        max_steps=_coerce_number(block.get("max_steps"), int, 12, "llm.max_steps"),
        max_pages=_coerce_number(block.get("max_pages"), int, 4, "llm.max_pages"),
        max_chars=_coerce_number(block.get("max_chars"), int, 6000, "llm.max_chars"),
    )


def _str_tuple(value: object) -> tuple[str, ...]:
    """Lowercased, stripped, non-empty strings of a yaml list; anything else → ``()``."""
    if not isinstance(value, list):
        return ()
    return tuple(text for item in value if (text := str(item).strip().lower().lstrip(".")))


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
    if value is None or isinstance(value, bool) or not isinstance(value, int | float | str):
        return default
    try:
        return cast(value)
    except ValueError as exc:
        raise ValueError(f"providers.yaml: {label} must be a number, got {value!r}") from exc


def _parse_names[T: str](raw: object, allowed: tuple[T, ...], label: str) -> tuple[T, ...]:
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


#: Renamed searcher ids: legacy id -> current id. Kept so existing configs, scripts and
#: docs that still say ``google_ground`` keep working after the rename to ``google_search``.
SEARCHER_ALIASES: dict[str, str] = {
    "google_ground": "google_search",
}


def canon_searcher_id(searcher_id: str) -> str:
    """Resolve a (possibly legacy) searcher id to its current id.

    Args:
        searcher_id (str): Id as written in config or on the command line.

    Returns:
        str: The current id; unchanged when it is not an alias.
    """
    return SEARCHER_ALIASES.get(searcher_id, searcher_id)


def get_searcher(config: ProvidersConfig, searcher_id: str) -> SearcherSpec:
    """Look up a searcher by id, accepting legacy aliases.

    Args:
        config (ProvidersConfig): Loaded registry.
        searcher_id (str): ``searchers[].id`` in YAML, or a legacy id.

    Returns:
        SearcherSpec: Matching spec.

    Raises:
        KeyError: If *searcher_id* is absent (after alias resolution).
    """
    wanted = canon_searcher_id(searcher_id)
    for spec in config.searchers:
        if spec.id == wanted:
            return spec
    raise KeyError(searcher_id)


# --- HTTP / JSON plumbing (fail closed) ----------------------------------------


@lru_cache(maxsize=64)
def _keychain_secret(name: str) -> str:
    """Read the named credential through the shared dedicated-Keychain vault."""
    from swarm_sdk import vault

    return vault.get(name) or ""


def _resolve_secret(name: str) -> str:
    return os.environ.get(name, "").strip() or _keychain_secret(name)


def env_keys(spec: SearcherSpec) -> list[str]:
    """Resolve every configured API key in order: the primary, then the fallbacks.

    Each name is read from the environment, then the Keychain. Names that do not resolve
    and duplicate values are skipped.

    Args:
        spec: Searcher configuration from ``providers.yaml``.

    Returns:
        list[str]: The non-empty keys, primary first.
    """
    keys: list[str] = []
    for name in (spec.api_key_env, *spec.api_key_fallback_envs):
        value = _resolve_secret(name) if name else ""
        if value and value not in keys:
            keys.append(value)
    return keys


def env_key(spec: SearcherSpec) -> str:
    """The first usable API key of ``spec`` (primary, else a fallback), or ``""``.

    Args:
        spec: Searcher configuration from ``providers.yaml``.

    Returns:
        str: The trimmed key, or an empty string if none resolves.
    """
    keys = env_keys(spec)
    return keys[0] if keys else ""


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


_HTTP_CLIENT: HttpxClient | None = None
_HTTP_CLIENT_LOCK = threading.Lock()
_EXECUTOR: ThreadPoolExecutor | None = None
_EXECUTOR_LOCK = threading.Lock()
_SEARCH_CACHE_TTL_S = 300.0
_SEARCH_CACHE_MAX = 256
_SEARCH_CACHE: OrderedDict[tuple[str, str, int], tuple[float, list[SearchHit], SearchFn]] = (
    OrderedDict()
)
_SEARCH_CACHE_LOCK = threading.Lock()
_REDIS_SEARCH_CACHE_LOCK = threading.Lock()
_REDIS_SEARCH_CACHE_URL = ""
_REDIS_SEARCH_CACHE: RedisExactCache | None = None


def _redis_search_cache() -> RedisExactCache | None:
    """Return the shared Redis search cache when REDIS_URL is configured."""
    global _REDIS_SEARCH_CACHE, _REDIS_SEARCH_CACHE_URL
    url = os.environ.get("REDIS_URL", "").strip()
    if not url:
        return None
    if url != _REDIS_SEARCH_CACHE_URL:
        with _REDIS_SEARCH_CACHE_LOCK:
            if url != _REDIS_SEARCH_CACHE_URL:
                _REDIS_SEARCH_CACHE = RedisExactCache(url, "websearch:results", 300)
                _REDIS_SEARCH_CACHE_URL = url
    return _REDIS_SEARCH_CACHE


def _redis_search_key(spec: SearcherSpec, fn: SearchFn, query: str) -> str:
    """Build a stable identity from provider configuration and exact query text."""
    module = getattr(fn, "__module__", type(fn).__module__)
    name = getattr(fn, "__qualname__", type(fn).__qualname__)
    function = f"{module}.{name}"
    return "\n".join(
        (
            spec.id,
            function,
            spec.kind,
            spec.engine or "",
            spec.base_url or "",
            spec.base_url_env or "",
            query,
        )
    )


def _encode_search_hits(hits: Sequence[SearchHit]) -> str:
    """Serialize compact search hit records, excluding per-call API token usage."""
    return json.dumps(
        [
            {
                "title": hit.title,
                "url": hit.url,
                "snippet": hit.snippet,
                "searcher_id": hit.searcher_id,
                "also_from": hit.also_from,
            }
            for hit in hits
        ],
        separators=(",", ":"),
    )


def _decode_search_hits(value: str) -> list[SearchHit] | None:
    """Deserialize search hits, rejecting malformed cache values as misses."""
    try:
        rows = json.loads(value)
    except json.JSONDecodeError:
        return None
    if not isinstance(rows, list):
        return None
    hits: list[SearchHit] = []
    for row in rows:
        if not isinstance(row, dict) or not all(
            isinstance(row.get(field), str) for field in ("title", "url", "snippet", "searcher_id")
        ):
            return None
        also_from = row.get("also_from", ())
        if not isinstance(also_from, (list, tuple)) or not all(
            isinstance(item, str) for item in also_from
        ):
            return None
        hits.append(
            SearchHit(
                title=row["title"],
                url=row["url"],
                snippet=row["snippet"],
                searcher_id=row["searcher_id"],
                also_from=tuple(also_from),
            )
        )
    return hits


def _cached_provider_search(
    spec: SearcherSpec,
    query: str,
    fn: SearchFn,
    ttl_s: float,
) -> list[SearchHit]:
    """Run one provider search with process-local and optional Redis caching."""
    if ttl_s <= 0:
        return list(fn(query, spec))
    cached = _search_cache_get(spec.id, query, fn)
    if cached is not None:
        return cached

    redis_cache = _redis_search_cache()
    redis_key = _redis_search_key(spec, fn, query)
    if redis_cache is not None:
        encoded = redis_cache.get(redis_key)
        if encoded is not None:
            cached = _decode_search_hits(encoded)
            if cached is not None:
                _search_cache_put(spec.id, query, fn, cached, ttl_s)
                return cached

    hits = list(fn(query, spec))
    _search_cache_put(spec.id, query, fn, hits, ttl_s)
    if redis_cache is not None:
        redis_cache.set(
            redis_key,
            _encode_search_hits(hits),
            ttl_s=max(1, int(ttl_s)),
        )
    return hits


def _search_cache_get(searcher_id: str, query: str, fn: SearchFn) -> list[SearchHit] | None:
    """Live cached hits for this (searcher, query) pair, or ``None``."""
    now = time.monotonic()
    with _SEARCH_CACHE_LOCK:
        key = (searcher_id, query, id(fn))
        entry = _SEARCH_CACHE.get(key)
        if entry is None:
            return None
        expires_at, hits, cached_fn = entry
        if now >= expires_at or cached_fn is not fn:
            del _SEARCH_CACHE[key]
            return None
        _SEARCH_CACHE.move_to_end(key)
        return hits


def _search_cache_put(
    searcher_id: str, query: str, fn: SearchFn, hits: list[SearchHit], ttl_s: float
) -> None:
    """Store hits with ``api_tokens`` zeroed: a cache hit costs no API call."""
    with _SEARCH_CACHE_LOCK:
        while len(_SEARCH_CACHE) >= _SEARCH_CACHE_MAX:
            _SEARCH_CACHE.popitem(last=False)
        _SEARCH_CACHE[(searcher_id, query, id(fn))] = (
            time.monotonic() + ttl_s,
            [replace(hit, api_tokens=0) for hit in hits],
            fn,
        )


def shared_http_client() -> HttpxClient:
    """Process-wide ``httpx.Client`` so TCP/TLS connections are reused."""
    global _HTTP_CLIENT
    if _HTTP_CLIENT is None:
        with _HTTP_CLIENT_LOCK:
            if _HTTP_CLIENT is None:
                import httpx

                try:
                    _HTTP_CLIENT = httpx.Client(http2=True)
                except ImportError:
                    # h2 optional: HTTP/2 multiplexing when present, else HTTP/1.1.
                    _HTTP_CLIENT = httpx.Client()
    return _HTTP_CLIENT


def shared_executor() -> ThreadPoolExecutor:
    """Process-wide worker pool; callers must never shut it down."""
    global _EXECUTOR
    if _EXECUTOR is None:
        with _EXECUTOR_LOCK:
            if _EXECUTOR is None:
                _EXECUTOR = ThreadPoolExecutor(
                    max_workers=_MAX_WORKERS, thread_name_prefix="websearch"
                )
    return _EXECUTOR


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
        response = shared_http_client().request(
            method,
            url,
            headers=headers,
            json=json_body,
            params=params,
            timeout=timeout_s,
        )
        response.raise_for_status()
        return _json_loads(response.content)
    except httpx.HTTPError as exc:
        raise OSError(str(exc)) from exc


def _json_loads(data: bytes | str) -> Any:
    """Parse JSON via orjson (orjson.JSONDecodeError subclasses json's)."""
    try:
        import orjson

        return orjson.loads(data)
    except ImportError:
        return json.loads(data)


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
    ) as exc:
        # Host and status only: httpx messages embed the full URL, which may carry a key.
        logger.warning(
            "%s %s failed: %s %s",
            method,
            urlsplit(url).netloc,
            type(exc).__name__,
            str(exc).split(" for url", 1)[0][:120],
        )
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


async def _bright_data_search(query: str, token: str, engine: str) -> object:
    """Call the hosted Bright Data MCP search tool using its in-memory token URL."""
    from mcp import Client

    url = "https://mcp.brightdata.com/mcp?" + urlencode({"token": token})
    async with Client(url) as client:
        result = await client.call_tool("search_engine", {"query": query, "engine": engine})
    if result.is_error:
        return None
    if result.structured_content is not None:
        return result.structured_content
    for block in result.content:
        value = getattr(block, "text", None)
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                continue
    return None


def _bright_data_hits(payload: object, searcher_id: str) -> list[SearchHit]:
    """Normalize Bright Data's Google JSON results into WebSearch hits."""
    if isinstance(payload, dict):
        for field in ("organic", "results", "organicResults", "data", "result"):
            if field in payload:
                return _bright_data_hits(payload[field], searcher_id)
    if not isinstance(payload, list):
        return []
    hits: list[SearchHit] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        href = row.get("link") or row.get("url")
        if not isinstance(href, str) or not href.startswith(("http://", "https://")):
            continue
        hits.append(
            SearchHit(
                title=str(row.get("title") or href),
                url=href,
                snippet=str(row.get("description") or row.get("snippet") or ""),
                searcher_id=searcher_id,
            )
        )
    return hits


def search_bright_data(query: str, spec: SearcherSpec) -> list[SearchHit]:
    """Search Bright Data's hosted MCP without storing its token in configuration."""
    token = env_key(spec)
    if not token:
        return []
    try:
        payload = asyncio.run(_bright_data_search(query, token, spec.engine or "google"))
    except Exception:  # noqa: BLE001 - provider boundary must not expose token-bearing URLs
        return []
    return _bright_data_hits(payload, spec.id)


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
    body: dict[str, Any] = {"api_key": token, "query": query, "max_results": 8}
    if spec.dork == "translate":
        parsed = parse_dork(query)
        if parsed.plain():
            body["query"] = parsed.plain()
        if parsed.sites:
            body["include_domains"] = list(parsed.sites)
        if parsed.exclude_sites:
            body["exclude_domains"] = list(parsed.exclude_sites)
        if parsed.after:
            body["start_date"] = parsed.after
        if parsed.before:
            body["end_date"] = parsed.before
    data = _httpx_json("POST", "https://api.tavily.com/search", json_body=body)
    if data is None:
        return []
    return hits_from_maps(
        dig(data, "results"), spec.id, title="title", url="url", snippet="content"
    )


def search_parallel(query: str, spec: SearcherSpec) -> list[SearchHit]:
    """Parallel Search API.

    The API uses an ``x-api-key`` header and accepts one or more search queries.
    ``spec.engine`` selects the documented search mode; ``dork: translate`` maps
    supported domain/date operators into ``advanced_settings.source_policy``.
    """
    token = env_key(spec)
    if not token:
        return []

    body: dict[str, Any] = {
        "objective": query,
        "search_queries": [query],
        "mode": spec.engine if spec.engine in {"turbo", "fast", "basic", "advanced"} else "fast",
        "advanced_settings": {"max_results": 8},
    }
    if spec.dork == "translate":
        parsed = parse_dork(query)
        if parsed.plain():
            body["objective"] = parsed.plain()
            body["search_queries"] = [parsed.plain()]
        source_policy: dict[str, Any] = {}
        if parsed.sites:
            source_policy["include_domains"] = list(parsed.sites)
        if parsed.exclude_sites:
            source_policy["exclude_domains"] = list(parsed.exclude_sites)
        if parsed.after:
            source_policy["after_date"] = parsed.after
        if source_policy:
            body["advanced_settings"]["source_policy"] = source_policy

    data = _httpx_json(
        "POST",
        "https://api.parallel.ai/v1/search",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-api-key": token,
        },
        json_body=body,
    )
    rows = dig(data, "results")
    if not isinstance(rows, list):
        return []
    normalized: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        excerpts = row.get("excerpts")
        snippet = (
            " ".join(str(item) for item in excerpts if item) if isinstance(excerpts, list) else ""
        )
        normalized.append(
            {
                "title": str(row.get("title") or ""),
                "url": str(row.get("url") or ""),
                "snippet": snippet,
            }
        )
    return hits_from_maps(normalized, spec.id, title="title", url="url", snippet="snippet")


def search_jina(query: str, spec: SearcherSpec) -> list[SearchHit]:
    """Jina Search Foundation API.

    ``POST https://s.jina.ai/`` with ``{"q": query}``. The documented JSON body
    is ``data[]`` of title, url, description, and content. ``JINA_BASE_URL``
    (``api.jina.ai/v1``) is the embeddings host and is not used here.

    Args:
        query: User query.
        spec: Needs ``JINA_API_KEY``.

    Returns:
        Cited pages, or ``[]`` when the key is missing or the call fails.
    """
    token = env_key(spec)
    if not token:
        return []
    root = env_base(spec) or "https://s.jina.ai"
    data = _httpx_json(
        "POST",
        f"{root}/",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json_body={"q": query, "num": 8},
    )
    rows = dig(data, "data")
    if not isinstance(rows, list):
        return []
    prepared: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        if not item.get("description") and isinstance(item.get("content"), str):
            item["description"] = item["content"][:280]
        prepared.append(item)
    hits = hits_from_maps(prepared, spec.id, title="title", url="url", snippet="description")
    usage = dig(prepared[0], "usage", "tokens") if prepared else None
    if hits and isinstance(usage, int):
        hits[0] = replace(hits[0], api_tokens=usage)
    return hits


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
    body: dict[str, Any] = {"query": query, "numResults": 8}
    # One short text preview per result; without this the API returns empty
    # snippets and agents get titles only.
    body["contents"] = {"text": {"maxCharacters": 300}}
    if spec.dork == "translate":
        parsed = parse_dork(query)
        if parsed.plain():
            body["query"] = parsed.plain()
        if parsed.sites:
            body["includeDomains"] = list(parsed.sites)
        if parsed.exclude_sites:
            body["excludeDomains"] = list(parsed.exclude_sites)
        if parsed.after:
            body["startPublishedDate"] = parsed.after
        if parsed.before:
            body["endPublishedDate"] = parsed.before
    data = _httpx_json(
        "POST",
        "https://api.exa.ai/search",
        headers={"x-api-key": token, "Content-Type": "application/json"},
        json_body=body,
    )
    if data is None:
        return []
    return hits_from_maps(dig(data, "results"), spec.id, title="title", url="url", snippet="text")


def search_openrouter_web(query: str, spec: SearcherSpec) -> list[SearchHit]:
    """OpenRouter web-search plugin: a cheap model runs a web search and cites sources.

    ``spec.engine`` is the OpenRouter model slug. The request enables ``plugins: [{"id":
    "web"}]``; the cited pages come back as ``url_citation`` annotations on the reply, one hit
    each. With ``dork: translate`` ``site:``/``-site:`` become ``include_domains`` /
    ``exclude_domains`` of the plugin and the remaining terms are the search text.

    Args:
        query (str): User query (a dork is translated, see above).
        spec (SearcherSpec): Needs ``OPENROUTER_API_KEY``; ``engine`` is the model.

    Returns:
        list[SearchHit]: Cited pages, or ``[]`` on a missing key or any API failure
        (401/402/429 are logged with host and status). The usage total is on the first hit.
    """
    keys = env_keys(spec)
    if not keys:
        return []
    plugin: dict[str, Any] = {"id": "web", "max_results": 8}
    text = query
    if spec.dork == "translate":
        parsed = parse_dork(query)
        text = parsed.plain() or query
        if parsed.sites:
            plugin["include_domains"] = list(parsed.sites)
        if parsed.exclude_sites:
            plugin["exclude_domains"] = list(parsed.exclude_sites)
    data = _httpx_json(
        "POST",
        f"{env_base(spec) or 'https://openrouter.ai/api/v1'}/chat/completions",
        headers={"Authorization": f"Bearer {keys[0]}", "Content-Type": "application/json"},
        json_body={
            "model": spec.engine or "openai/gpt-oss-20b:free",
            "messages": [
                {
                    "role": "user",
                    "content": f"Search the web for: {text}\nReply with one short sentence.",
                }
            ],
            "plugins": [plugin],
            "max_tokens": 64,
        },
        timeout_s=60.0,
    )
    annotations = dig(data, "choices")
    message = (
        dig(annotations[0], "message") if isinstance(annotations, list) and annotations else None
    )
    notes = dig(message, "annotations")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for note in notes if isinstance(notes, list) else []:
        if not isinstance(note, dict) or note.get("type") != "url_citation":
            continue
        cite = note.get("url_citation")
        info = cite if isinstance(cite, dict) else note  # chat-completions nests, responses is flat
        url = info.get("url")
        if isinstance(url, str) and url not in seen:
            seen.add(url)
            rows.append(
                {
                    "url": url,
                    "title": info.get("title") or url,
                    "snippet": info.get("content") or "",
                }
            )
    hits = hits_from_maps(rows, spec.id, title="title", url="url", snippet="snippet")
    total = dig(data, "usage", "total_tokens")
    if hits and isinstance(total, int):
        hits[0] = replace(hits[0], api_tokens=total)
    return hits


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


_ROTATE_STATUSES = frozenset({401, 403, 429})
_STATUS = re.compile(r"\b([1-5]\d\d)\b")


def _http_status(exc: BaseException) -> int | None:
    """HTTP status in an ``OSError`` raised by :func:`request_json`, else ``None``."""
    head = str(exc).split(" for url", 1)[0]
    match = _STATUS.search(head)
    return int(match.group(1)) if match else None


def search_google_search(query: str, spec: SearcherSpec) -> list[SearchHit]:
    """Gemini with Google Search grounding; returns the cited web sources.

    ``spec.engine`` is the model id, ``spec.base_url`` the API root. Keys come from
    ``api_key_env`` then ``api_key_env_fallbacks``; a 401, 403 or 429 (bad key, quota)
    moves on to the next key, any other failure stops. Cited URIs are Google redirect
    links; the midend follows redirects when scraping. The response is the documented
    ``generateContent`` shape (``groundingMetadata`` with ``groundingChunks`` and
    ``groundingSupports``).

    Args:
        query (str): User query (dork strings work as-is).
        spec (SearcherSpec): Searcher configuration.

    Returns:
        list[SearchHit]: One hit per grounding chunk. The API-reported token total
        is stored on the first hit. ``[]`` without a key or on failure.
    """
    keys = env_keys(spec)
    if not keys:
        return []
    root = env_base(spec) or "https://generativelanguage.googleapis.com/v1beta"
    model = spec.engine or "gemini-3.5-flash"
    body = {"contents": [{"parts": [{"text": query}]}], "tools": [{"google_search": {}}]}
    data: Any = None
    for index, token in enumerate(keys, start=1):
        try:
            data = request_json(
                "POST",
                f"{root}/models/{model}:generateContent",
                headers={"x-goog-api-key": token, "Content-Type": "application/json"},
                json_body=body,
                timeout_s=60.0,
            )
            break
        except (TimeoutError, OSError, ConnectionError, ValueError) as exc:
            status = _http_status(exc)
            # Host and status only: the message embeds the request URL.
            logger.warning(
                "google_search key %d/%d failed: %s %s",
                index,
                len(keys),
                type(exc).__name__,
                status or "",
            )
            if status not in _ROTATE_STATUSES:
                return []
    if data is None:
        return []
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
    queries = dig(meta, "webSearchQueries")
    logger.info(
        "google_search: %s search queries run by %s (Gemini 3 bills per query)",
        len(queries) if isinstance(queries, list) else 0,
        model,
    )
    total = dig(data, "usageMetadata", "totalTokenCount")
    if hits and isinstance(total, int):
        hits[0] = replace(hits[0], api_tokens=total)
    return hits


def search_kimi(query: str, spec: SearcherSpec) -> list[SearchHit]:
    """Moonshot Kimi Web Search Basic API.

    Uses the standalone ``POST /v1/tools/search`` endpoint so returned URLs,
    titles and snippets are available directly (the legacy ``$web_search`` tool
    keeps them inside the model turn). ``spec.engine`` is the model hint used
    only for logging; the search endpoint itself does not take a ``model`` field.

    Args:
        query (str): User query.
        spec (SearcherSpec): Needs ``MOONSHOT_API_KEY``; ``base_url_env`` is
            ``MOONSHOT_BASE_URL`` (default https://api.moonshot.ai).

    Returns:
        list[SearchHit]: Results, or ``[]`` on missing key / failure.
    """
    token = env_key(spec)
    if not token:
        return []
    body: dict[str, Any] = {"text_query": query, "limit": 8, "timeout_seconds": 30}
    if spec.dork == "translate":
        parsed = parse_dork(query)
        if parsed.plain():
            body["text_query"] = parsed.plain()
        if parsed.sites:
            body["sites"] = list(parsed.sites)[:5]
        if parsed.after or parsed.before:
            body["time_window"] = {}
            if parsed.after:
                body["time_window"]["start"] = parsed.after
            if parsed.before:
                body["time_window"]["end"] = parsed.before
    root = env_base(spec) or "https://api.moonshot.ai"
    data = _httpx_json(
        "POST",
        f"{root}/v1/tools/search",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json_body=body,
        timeout_s=60.0,
    )
    if data is None:
        return []
    return hits_from_maps(
        dig(data, "search_results"), spec.id, title="title", url="url", snippet="snippet"
    )


def search_ddg(query: str, spec: SearcherSpec) -> list[SearchHit]:
    """DuckDuckGo text search via ``ddgs`` (the renamed ``duckduckgo-search``).

    The old ``duckduckgo_search`` package is only a fallback: it now returns no results.

    Args:
        query (str): User query.
        spec (SearcherSpec): Registry entry (no API key needed).

    Returns:
        list[SearchHit]: Results, or ``[]`` if the package is missing or the call fails.
    """
    del spec
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS  # ty: ignore[unresolved-import]
        except ImportError as exc:
            raise OSError("ddgs not installed (uv sync --extra websearch)") from exc

    try:
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=10)
    except Exception as exc:
        logger.warning("ddg search failed: %s", type(exc).__name__)
        return []
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


def search_ddg_lite(query: str, spec: SearcherSpec) -> list[SearchHit]:
    """DuckDuckGo Lite: scrape the plain-HTML endpoint, no API key or package.

    Independent of the ``ddgs`` package used by :func:`search_ddg`, so one
    flaky backend does not take out both.

    Args:
        query (str): User query.
        spec (SearcherSpec): Registry entry (no API key needed).

    Returns:
        list[SearchHit]: Results, or ``[]`` when selectolax is missing or the
        page cannot be fetched/parsed.
    """
    try:
        from selectolax.parser import HTMLParser
    except ImportError as exc:
        raise OSError("selectolax not installed (uv sync --extra websearch)") from exc

    client = shared_http_client()
    # The bare library client gets a 202 anomaly page; browser-ish headers pass.
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        ),
        "Referer": "https://lite.duckduckgo.com/",
    }
    try:
        response = client.get(
            "https://lite.duckduckgo.com/lite/", params={"q": query}, headers=headers
        )
        response.raise_for_status()
    except Exception as exc:
        logger.warning("ddg-lite failed: %s", type(exc).__name__)
        return []
    tree = HTMLParser(response.text)
    links = tree.css("a.result-link")
    snippets = tree.css("td.result-snippet")
    hits: list[SearchHit] = []
    for index, link in enumerate(links):
        url = _unwrap_lite_href(str(link.attributes.get("href") or ""))
        if not url:
            continue
        hits.append(
            SearchHit(
                title=link.text(strip=True) or url,
                url=url,
                snippet=snippets[index].text(strip=True) if index < len(snippets) else "",
                searcher_id=spec.id,
            )
        )
    return hits


def _unwrap_lite_href(href: str) -> str:
    """Resolve a DuckDuckGo Lite redirect href to its target URL."""
    from urllib.parse import parse_qs

    if href.startswith("//"):
        href = f"https:{href}"
    if "duckduckgo.com/l/?" not in href:
        return href if href.startswith("http") else ""
    target = parse_qs(urlsplit(href).query).get("uddg", [""])[0]
    return target if target.startswith("http") else ""


def builtin_searchers() -> dict[str, SearchFn]:
    """Named HTTP searchers from ``providers.yaml`` ids.

    Returns:
        dict[str, SearchFn]: brave, ddg, tavily, apify, exa, searxng.
    """
    return {
        "bright_data": search_bright_data,
        "brave": search_brave,
        "ddg": search_ddg,
        "ddglite": search_ddg_lite,
        "tavily": search_tavily,
        "parallel": search_parallel,
        "jina": search_jina,
        "apify": search_apify,
        "exa": search_exa,
        "openrouter_web": search_openrouter_web,
        "google_search": search_google_search,
        # Legacy id, kept so existing configs keep working.
        "google_ground": search_google_search,
        "searxng": search_searxng,
        "kimisearch": search_kimi,
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
    cache_ttl_s: float = _SEARCH_CACHE_TTL_S,
) -> list[SearchHit]:
    """Run ``query`` on YAML searchers until one returns hits.

    Args:
        query (str): User query.
        config (ProvidersConfig | None): Registry; default ``load_providers()``.
        backends (Mapping[str, SearchFn] | None): id → callable. Default HTTP APIs.
        searcher_id (str | None): Restrict to one id.
        cache_ttl_s (float): Provider result TTL; non-positive values disable caching.

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
        provider_hits = _cached_provider_search(spec, query, fn, cache_ttl_s)
        hits.extend(prefilter_hits(provider_hits, cfg.prefilter)[0])
        if hits:
            break
    return hits


def _select_specs(config: ProvidersConfig, searcher_id: str | None) -> list[SearcherSpec]:
    specs = list(config.searchers)
    if searcher_id is None:
        return specs
    wanted = canon_searcher_id(searcher_id)
    specs = [s for s in specs if s.id == wanted]
    if not specs:
        raise KeyError(searcher_id)
    return specs


def _rrf_fuse(batches: Sequence[Sequence[SearchHit]], *, k: int = 60) -> list[SearchHit]:
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
    cache_ttl_s: float = _SEARCH_CACHE_TTL_S,
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
        cache_ttl_s (float): Per-(searcher, query) result cache lifetime;
            ``<= 0`` (default) disables caching — opt in at the pipeline level.
            Cached hits report no API tokens.

    Returns:
        list[SearchHit]: Unique hits from all searchers, best first.

    Raises:
        KeyError: If ``searcher_id`` is not in the registry.
    """
    from WebSearch.backend.prefilter import prefilter_hits
    from WebSearch.frontend.hits import near_dedupe, normalize_hit

    cfg = config or load_providers()
    table = dict(backends if backends is not None else builtin_searchers())
    jobs = [(spec, table[spec.id]) for spec in _select_specs(cfg, searcher_id) if spec.id in table]
    if not jobs:
        return []

    semaphore = threading.Semaphore(max(1, min(max_workers, len(jobs))))

    def run(job: tuple[SearcherSpec, SearchFn]) -> Sequence[SearchHit]:
        spec, fn = job
        with semaphore:
            try:
                return _cached_provider_search(spec, query, fn, cache_ttl_s)
            except TimeoutError, OSError, ConnectionError, ValueError:
                logger.warning("searcher %s failed", spec.id, exc_info=True)
                return []

    executor = shared_executor()
    wait = timeout_s if timeout_s and timeout_s > 0 else None
    index_by_future = {executor.submit(run, job): index for index, job in enumerate(jobs)}
    by_index: dict[int, Sequence[SearchHit]] = {}
    try:
        for future in as_completed(index_by_future, timeout=wait):
            try:
                by_index[index_by_future[future]] = future.result()
            except Exception:
                logger.warning("searcher crashed", exc_info=True)
    except TimeoutError:
        for future in index_by_future:
            future.cancel()
        logger.warning("search budget %ss exceeded; abandoning slow searchers", timeout_s)
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
    logger.debug("sink stored=%d skipped=%d %s", report.stored, report.skipped, report.detail)


#: Legacy name for :func:`search_google_search` (the searcher id was ``google_ground``).
search_google_ground = search_google_search


__all__ = [
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
    "search_searxng",
    "search_tavily",
    "search_jina",
    "search_kimi",
    "searcher_ids",
    "type_is_hit",
    "type_is_searcher_kind",
]
