"""Tests for shared Redis caching of WebSearch provider results."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from types import ModuleType, SimpleNamespace
from typing import Any, ClassVar

import pytest

from WebSearch.frontend import SearchHit, parallel_search, registry_search
from WebSearch.frontend import websearchers
from WebSearch.frontend.websearchers import ProvidersConfig, SearcherSpec


class _RedisError(Exception):
    """Fake Redis client error."""


class _MemoryRedis:
    """In-memory stand-in for a Redis server and connection pool."""

    instance: ClassVar[_MemoryRedis]

    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.fail = False

    @classmethod
    def from_url(cls, url: str, **kwargs: Any) -> _MemoryRedis:
        """Return the shared fake client."""
        del url, kwargs
        return cls.instance

    def get(self, key: str) -> bytes | None:
        """Return one value or raise a fake connection error."""
        if self.fail:
            raise _RedisError("unavailable")
        return self.values.get(key)

    def set(self, key: str, value: bytes, *, ex: int) -> bool:
        """Store one value."""
        del ex
        if self.fail:
            raise _RedisError("unavailable")
        self.values[key] = value
        return True


@pytest.fixture
def redis_state(monkeypatch: pytest.MonkeyPatch) -> _MemoryRedis:
    """Install a fake redis-py module and clear process-local WebSearch caches."""
    client = _MemoryRedis()
    _MemoryRedis.instance = client
    module = ModuleType("redis")
    setattr(module, "Redis", _MemoryRedis)
    setattr(module, "exceptions", SimpleNamespace(RedisError=_RedisError))
    monkeypatch.setitem(sys.modules, "redis", module)
    monkeypatch.setenv("REDIS_URL", "redis://cache.invalid/0")
    monkeypatch.setattr(websearchers, "_REDIS_SEARCH_CACHE", None)
    monkeypatch.setattr(websearchers, "_REDIS_SEARCH_CACHE_URL", "")
    with websearchers._SEARCH_CACHE_LOCK:
        websearchers._SEARCH_CACHE.clear()
    return client


def _config() -> ProvidersConfig:
    """Return one provider configuration for cache tests."""
    return ProvidersConfig(
        version=1,
        searchers=(SearcherSpec(id="fake", kind="websearcher"),),
        extractor_order=("regex",),
    )


def test_parallel_search_reuses_redis_hits_without_provider_tokens(
    redis_state: _MemoryRedis,
) -> None:
    """Reuse results across process-local cache resets without counting API tokens twice."""
    calls = 0
    source = [SearchHit("Title", "https://example.test", "Snippet", "fake", api_tokens=7)]

    def backend(query: str, spec: SearcherSpec) -> Sequence[SearchHit]:
        nonlocal calls
        del query, spec
        calls += 1
        return source

    first = parallel_search("fresh query", config=_config(), backends={"fake": backend})
    with websearchers._SEARCH_CACHE_LOCK:
        websearchers._SEARCH_CACHE.clear()
    second = parallel_search("fresh query", config=_config(), backends={"fake": backend})

    assert calls == 1
    assert first[0].api_tokens == 7
    assert second[0].api_tokens == 0
    assert second[0].url == source[0].url
    assert redis_state.values


def test_registry_search_can_disable_local_and_redis_caching(
    redis_state: _MemoryRedis,
) -> None:
    """Honor a non-positive TTL in the ordered provider-search path."""
    calls = 0

    def backend(query: str, spec: SearcherSpec) -> Sequence[SearchHit]:
        nonlocal calls
        del query
        calls += 1
        return [SearchHit("Title", "https://example.test", "Snippet", spec.id)]

    registry_search("uncached", config=_config(), backends={"fake": backend}, cache_ttl_s=0)
    registry_search("uncached", config=_config(), backends={"fake": backend}, cache_ttl_s=0)

    assert calls == 2
    assert redis_state.values == {}
