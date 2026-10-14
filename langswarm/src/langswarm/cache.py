"""Redis access for caching and shared state (``redis`` extra)."""


def redis_client(url: str | None = None):
    """Lazily build an async redis-py client; connections dial on first use."""
    import os

    from redis.asyncio import Redis

    return Redis.from_url(
        url or os.environ.get("LANGSWARM_REDIS_URL", "redis://localhost:6379"),
        decode_responses=True,
    )
