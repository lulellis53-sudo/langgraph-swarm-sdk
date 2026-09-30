"""Frontend websearchers — named backends from ``providers.yaml``.

Live MCP/HTTP calls can be injected. Default backends are HTTP APIs in
``frontend.apis`` (fail closed without keys / on errors).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from WebSearch.frontend.providers import ProvidersConfig, SearcherSpec, load_providers

SearchFn = Callable[[str, SearcherSpec], Sequence["SearchHit"]]


@dataclass(frozen=True, slots=True)
class SearchHit:
    title: str
    url: str
    snippet: str
    searcher_id: str


class WebSearcher(Protocol):
    spec: SearcherSpec

    def search(self, query: str) -> Sequence[SearchHit]: ...


def type_is_hit(value: object) -> bool:
    """Return whether *value* is a ``SearchHit``.

    Args:
        value (object): Candidate object.

    Returns:
        bool: True if ``SearchHit``.
    """
    return isinstance(value, SearchHit)


def searcher_ids(config: ProvidersConfig | None = None) -> tuple[str, ...]:
    """List searcher ids from config order.

    Args:
        config (ProvidersConfig | None): Loaded YAML; default from disk.

    Returns:
        tuple[str, ...]: ``searchers[].id`` values.
    """
    cfg = config or load_providers()
    return tuple(spec.id for spec in cfg.searchers)


def _default_backends() -> Mapping[str, SearchFn]:
    from WebSearch.frontend.apis import builtin_searchers

    return builtin_searchers()


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
    cfg = config or load_providers()
    table = dict(_default_backends() if backends is None else backends)
    specs = list(cfg.searchers)
    if searcher_id is not None:
        specs = [s for s in specs if s.id == searcher_id]
        if not specs:
            raise KeyError(searcher_id)
    hits: list[SearchHit] = []
    for spec in specs:
        fn = table.get(spec.id)
        if fn is None:
            continue
        hits.extend(fn(query, spec))
        if hits:
            break
    return hits


__all__ = [
    "SearchFn",
    "SearchHit",
    "WebSearcher",
    "registry_search",
    "searcher_ids",
    "type_is_hit",
]
