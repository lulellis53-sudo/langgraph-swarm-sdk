"""Providers registry: load and parse ``providers.yaml`` / ``.json`` / ``.toml``."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml

from WebSearch.frontend.types import (
    _CRAWLERS,
    _EXTRACTORS,
    CrawlSpec,
    LlmSpec,
    PrefilterPolicy,
    ProvidersConfig,
    SearcherKind,
    SearcherSpec,
)

logger = logging.getLogger(__name__)

#: Renamed searcher ids: legacy id -> current id.
SEARCHER_ALIASES: dict[str, str] = {
    "google_ground": "google_search",
}

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
DEFAULT_AUTONOMOUS_SUMMARIZE: tuple[str, ...] = (
    "google:gemini-3.5-flash",
    "cohere:command-r7b",
    "groq:openai/gpt-oss-20b",
)
DEFAULT_AUTONOMOUS_MEMORY: tuple[str, ...] = ("mem0",)
DEFAULT_AUTONOMOUS_DECISION: tuple[str, ...] = ("jev",)

_PROVIDERS_CACHE: dict[tuple[str, int, int], ProvidersConfig] = {}


def providers_yaml_path() -> Path:
    """Return the path to the packaged ``providers.yaml``."""
    return Path(str(files("WebSearch").joinpath("providers.yaml")))


def providers_config_path() -> Path:
    """Resolve the providers file: ``WEBSEARCH_PROVIDERS``, else yaml, else json."""
    override = os.environ.get("WEBSEARCH_PROVIDERS", "").strip()
    if override:
        return Path(override).expanduser()
    yaml_path = providers_yaml_path()
    json_path = yaml_path.with_suffix(".json")
    return json_path if (not yaml_path.exists() and json_path.exists()) else yaml_path


def _json_loads(data: bytes | str) -> Any:
    """Parse JSON via orjson when available (JSONDecodeError subclasses json's)."""
    try:
        import orjson

        return orjson.loads(data)
    except ImportError:
        return json.loads(data)


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
    """Return whether *value* is a known ``SearcherKind``."""
    return value in ("docs", "websearcher")


def load_providers(path: Path | None = None) -> ProvidersConfig:
    """Parse the providers file (YAML or JSON), cached per file version.

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
    """Parse one providers file into a :class:`ProvidersConfig`."""
    raw_obj = _read_mapping(target)
    if not isinstance(raw_obj, dict):
        raise ValueError(f"{target.name}: expected a mapping at the top level")
    raw: dict[str, object] = raw_obj
    searchers: list[SearcherSpec] = []
    items = raw.get("searchers")
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            raise ValueError("each searchers[] entry must be a mapping")
        kind_raw = item.get("kind")
        if not type_is_searcher_kind(kind_raw):
            raise ValueError(f"searcher {item.get('id')!r}: unknown kind {kind_raw!r}")
        kind: SearcherKind = kind_raw  # type: ignore[assignment]
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
        enabled_raw = item.get("enabled")
        enabled = bool(enabled_raw) if enabled_raw is not None else True
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
                enabled=enabled,
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


def canon_searcher_id(searcher_id: str) -> str:
    """Resolve a (possibly legacy) searcher id to its current id."""
    return SEARCHER_ALIASES.get(searcher_id, searcher_id)


def get_searcher(config: ProvidersConfig, searcher_id: str) -> SearcherSpec:
    """Look up a searcher by id, accepting legacy aliases.

    Raises:
        KeyError: If *searcher_id* is absent (after alias resolution).
    """
    wanted = canon_searcher_id(searcher_id)
    for spec in config.searchers:
        if spec.id == wanted:
            return spec
    raise KeyError(searcher_id)
