"""Small optional Redis cache for exact string-keyed values."""

from __future__ import annotations

import hashlib
import logging

logger = logging.getLogger(__name__)
_MAX_VALUE_BYTES = 262_144
_MAX_CONNECTIONS = 8
_SOCKET_TIMEOUT_S = 0.1


class RedisExactCache:
    """Store bounded UTF-8 values in Redis with a namespace and expiration."""

    def __init__(self, url: str, namespace: str, ttl_s: int) -> None:
        """Build a pooled Redis client without connecting until the first operation."""
        parts = namespace.strip(":").split(":")
        if not namespace or any(not part for part in parts):
            raise ValueError("namespace must contain non-empty colon-separated segments")
        if ttl_s < 1:
            raise ValueError("ttl_s must be at least 1")
        try:
            import redis
        except ImportError as exc:
            raise ImportError("Redis caching requires the optional 'redis' dependency") from exc

        self._redis = redis.Redis.from_url(
            url,
            decode_responses=False,
            max_connections=_MAX_CONNECTIONS,
            socket_connect_timeout=_SOCKET_TIMEOUT_S,
            socket_timeout=_SOCKET_TIMEOUT_S,
            health_check_interval=30,
        )
        self._redis_error = redis.exceptions.RedisError
        self._namespace = namespace.strip(":")
        self._ttl_s = ttl_s

    def get(self, key: str) -> str | None:
        """Return one cached UTF-8 value, or None on a miss or Redis error."""
        try:
            value = self._redis.get(self._key(key))
        except self._redis_error as exc:
            logger.debug("Redis cache read failed: %s", type(exc).__name__)
            return None
        if value is None:
            return None
        try:
            return value.decode("utf-8") if isinstance(value, bytes) else str(value)
        except UnicodeDecodeError:
            return None

    def set(self, key: str, value: str, *, ttl_s: int | None = None) -> bool:
        """Store a UTF-8 value unless it exceeds the per-entry memory limit."""
        lifetime = self._ttl_s if ttl_s is None else ttl_s
        if lifetime < 1:
            return False
        encoded = value.encode("utf-8")
        if len(encoded) > _MAX_VALUE_BYTES:
            return False
        try:
            return bool(self._redis.set(self._key(key), encoded, ex=lifetime))
        except self._redis_error as exc:
            logger.debug("Redis cache write failed: %s", type(exc).__name__)
            return False

    def _key(self, key: str) -> str:
        """Build a short versioned key without exposing the original cache input."""
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return f"{self._namespace}:v1:{digest}"


__all__ = ["RedisExactCache"]
