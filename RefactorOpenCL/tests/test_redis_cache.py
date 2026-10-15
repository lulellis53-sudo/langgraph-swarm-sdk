"""Tests for optional Redis exact caching and fallback behavior."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, ClassVar

import pytest

from swarm_sdk.retrieval.cache import SemanticCache
from swarm_sdk.retrieval.embeddings import HashEmbedder
from swarm_sdk.retrieval.redis_exact import RedisExactCache


class _RedisError(Exception):
    """Fake Redis client error."""


class _MemoryRedis:
    """In-memory stand-in for the redis-py connection pool."""

    instance: ClassVar[_MemoryRedis]
    last_options: ClassVar[dict[str, Any]] = {}

    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.expirations: dict[str, int] = {}
        self.fail = False

    @classmethod
    def from_url(cls, url: str, **kwargs: Any) -> _MemoryRedis:
        """Create the shared fake client and retain connection options."""
        del url
        cls.last_options = kwargs
        if not hasattr(cls, "instance"):
            cls.instance = cls()
        return cls.instance

    def get(self, key: str) -> bytes | None:
        """Return a value or raise the configured connection error."""
        if self.fail:
            raise _RedisError("unavailable")
        return self.values.get(key)

    def set(self, key: str, value: bytes, *, ex: int) -> bool:
        """Store a value and its expiration."""
        if self.fail:
            raise _RedisError("unavailable")
        self.values[key] = value
        self.expirations[key] = ex
        return True


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> _MemoryRedis:
    """Install a minimal redis-py module with one shared in-memory database."""
    _MemoryRedis.instance = _MemoryRedis()
    module = ModuleType("redis")
    setattr(module, "Redis", _MemoryRedis)
    setattr(module, "exceptions", SimpleNamespace(RedisError=_RedisError))
    monkeypatch.setitem(sys.modules, "redis", module)
    return _MemoryRedis.instance


def test_redis_exact_cache_hashes_keys_and_sets_ttl(fake_redis: _MemoryRedis) -> None:
    """Keep original cache inputs out of Redis keys and expire values."""
    cache = RedisExactCache("redis://cache.invalid/0", "test:responses", 60)

    assert cache.set("private prompt", "cached response")
    redis_key = next(iter(fake_redis.values))
    assert redis_key.startswith("test:responses:v1:")
    assert "private prompt" not in redis_key
    assert cache.get("private prompt") == "cached response"
    assert fake_redis.expirations[redis_key] == 60
    assert _MemoryRedis.last_options["max_connections"] == 8
    assert _MemoryRedis.last_options["socket_timeout"] == 0.1


def test_redis_errors_and_oversized_values_are_cache_misses(fake_redis: _MemoryRedis) -> None:
    """Fail open on Redis errors and skip values above the memory bound."""
    cache = RedisExactCache("redis://cache.invalid/0", "test:responses", 60)
    assert not cache.set("large", "x" * 262_145)

    fake_redis.fail = True
    assert cache.get("missing") is None
    assert not cache.set("write", "value")


def test_semantic_cache_uses_redis_before_local_semantic_lookup(
    tmp_path: Path,
    fake_redis: _MemoryRedis,
) -> None:
    """Share exact responses through Redis while leaving SQLite as local fallback."""
    first = SemanticCache(
        str(tmp_path / "first.db"),
        HashEmbedder(16),
        redis_url="redis://cache.invalid/0",
        redis_ttl_s=90,
    )
    first.store("same prompt", "shared answer")

    second = SemanticCache(
        str(tmp_path / "second.db"),
        HashEmbedder(16),
        redis_url="redis://cache.invalid/0",
        redis_ttl_s=90,
    )
    assert second.lookup("same prompt") == "shared answer"
    assert second.stats()["exact_hits"] == 1
    assert fake_redis.expirations


def test_semantic_cache_redis_keys_are_tenant_scoped(
    tmp_path: Path,
    fake_redis: _MemoryRedis,
) -> None:
    """Share Redis responses only within the tenant that stored them."""
    first = SemanticCache(
        str(tmp_path / "tenant-a.db"),
        HashEmbedder(16),
        redis_url="redis://cache.invalid/0",
    )
    first.store("same prompt", "tenant a answer", tenant_id="tenant-a")

    second = SemanticCache(
        str(tmp_path / "tenant-b.db"),
        HashEmbedder(16),
        redis_url="redis://cache.invalid/0",
    )
    assert second.lookup("same prompt", tenant_id="tenant-b") is None
    assert second.lookup("same prompt", tenant_id="tenant-a") == "tenant a answer"
