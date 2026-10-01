"""Load ``providers.yaml`` — searcher registry, crawlers, and extractors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

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
    id: str
    kind: SearcherKind
    api_key_env: str | None = None
    engine: str | None = None
    description: str = ""
    base_url: str | None = None
    base_url_env: str | None = None


@dataclass(frozen=True, slots=True)
class CrawlSpec:
    timeout_s: float = 20.0
    max_bytes: int = 1_048_576
    max_urls: int = 8
    schemes: tuple[str, ...] = ("http", "https")
    crawler_order: tuple[CrawlerName, ...] = _CRAWLERS


@dataclass(frozen=True, slots=True)
class PrefilterPolicy:
    schemes: tuple[str, ...] = ("http", "https")
    blocked_domains: tuple[str, ...] = ()
    min_snippet_chars: int = 0
    require_title: bool = True


@dataclass(frozen=True, slots=True)
class ProvidersConfig:
    version: int
    searchers: tuple[SearcherSpec, ...]
    extractor_order: tuple[ExtractorName, ...]
    crawl: CrawlSpec = field(default_factory=CrawlSpec)
    prefilter: PrefilterPolicy = field(default_factory=PrefilterPolicy)


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


__all__ = [
    "CrawlerName",
    "CrawlSpec",
    "ExtractorName",
    "PrefilterPolicy",
    "ProvidersConfig",
    "SearcherKind",
    "SearcherSpec",
    "get_searcher",
    "load_providers",
    "providers_yaml_path",
    "type_is_searcher_kind",
]
