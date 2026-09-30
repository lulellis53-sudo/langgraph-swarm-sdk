"""Load ``providers.yaml`` — searcher registry and extractor/crawl settings."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

SearcherKind = Literal["docs", "websearcher"]
ExtractorName = Literal["selectolax", "trafilatura", "bs4"]


@dataclass(frozen=True, slots=True)
class SearcherSpec:
    id: str
    kind: SearcherKind
    api_key_env: str | None = None
    engine: str | None = None
    description: str = ""


@dataclass(frozen=True, slots=True)
class CrawlSpec:
    timeout_s: float = 20.0
    max_bytes: int = 1_048_576
    max_urls: int = 8
    schemes: tuple[str, ...] = ("http", "https")


@dataclass(frozen=True, slots=True)
class ProvidersConfig:
    version: int
    searchers: tuple[SearcherSpec, ...]
    extractor_order: tuple[ExtractorName, ...]
    crawl: CrawlSpec = field(default_factory=CrawlSpec)


def providers_yaml_path() -> Path:
    return Path(__file__).resolve().parents[1] / "providers.yaml"


def type_is_searcher_kind(value: object) -> bool:
    return value in ("docs", "websearcher")


def load_providers(path: Path | None = None) -> ProvidersConfig:
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
        searchers.append(
            SearcherSpec(
                id=str(item["id"]),
                kind=kind,
                api_key_env=str(env) if isinstance(env, str) else None,
                engine=str(item["engine"]) if isinstance(item.get("engine"), str) else None,
                description=str(item.get("description") or ""),
            )
        )
    extractors_block = raw.get("extractors")
    order_raw = (
        extractors_block.get("order")
        if isinstance(extractors_block, dict)
        else None
    ) or [
        "selectolax",
        "trafilatura",
        "bs4",
    ]
    order: list[ExtractorName] = []
    for name in order_raw:
        if name == "selectolax":
            order.append("selectolax")
        elif name == "trafilatura":
            order.append("trafilatura")
        elif name == "bs4":
            order.append("bs4")
        else:
            raise ValueError(f"unknown extractor: {name!r}")
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
        extractor_order=tuple(order),
        crawl=CrawlSpec(
            timeout_s=float(timeout_val) if isinstance(timeout_val, (int, float, str)) else 20.0,
            max_bytes=int(bytes_val) if isinstance(bytes_val, (int, float, str)) else 1_048_576,
            max_urls=int(urls_val) if isinstance(urls_val, (int, float, str)) else 8,
            schemes=schemes,
        ),
    )


def get_searcher(config: ProvidersConfig, searcher_id: str) -> SearcherSpec:
    for spec in config.searchers:
        if spec.id == searcher_id:
            return spec
    raise KeyError(searcher_id)


__all__ = [
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
