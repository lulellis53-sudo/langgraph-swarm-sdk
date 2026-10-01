"""Load ``providers.yaml`` — searcher registry, crawlers, and extractors."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

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
class ProvidersConfig:
    version: int
    searchers: tuple[SearcherSpec, ...]
    extractor_order: tuple[ExtractorName, ...]
    crawl: CrawlSpec = field(default_factory=CrawlSpec)


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
        ValueError: If YAML is not a mapping or names an unknown extractor/crawler.
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
                engine=str(item["engine"]) if isinstance(item.get("engine"), str) else None,
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
    timeout_val = crawl_raw.get("timeout_s")
    bytes_val = crawl_raw.get("max_bytes")
    urls_val = crawl_raw.get("max_urls")
    return ProvidersConfig(
        version=int(raw.get("version") or 1),
        searchers=tuple(searchers),
        extractor_order=order,
        crawl=CrawlSpec(
            timeout_s=float(timeout_val) if isinstance(timeout_val, int | float | str) else 20.0,
            max_bytes=int(bytes_val) if isinstance(bytes_val, int | float | str) else 1_048_576,
            max_urls=int(urls_val) if isinstance(urls_val, int | float | str) else 8,
            schemes=schemes,
            crawler_order=crawler_order,
        ),
    )


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
    "ProvidersConfig",
    "SearcherKind",
    "SearcherSpec",
    "get_searcher",
    "load_providers",
    "providers_yaml_path",
    "type_is_searcher_kind",
]
