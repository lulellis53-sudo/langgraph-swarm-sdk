"""Checkpointer factories: short-term swarm state.

Three tiers: in-memory (default), SQLite (one file, zero infrastructure), and
Redis (durable, multi-process). Each backend module is imported inside the
factory, so its dependency is only required when actually selected.
"""


def build_checkpointer(kind: str = "memory"):
    """Return a LangGraph checkpointer of the requested kind."""
    if kind == "memory":
        from langgraph.checkpoint.memory import InMemorySaver

        return InMemorySaver()

    if kind == "sqlite":
        import sqlite3

        from langgraph.checkpoint.sqlite import SqliteSaver

        return SqliteSaver(sqlite3.connect("langswarm.db", check_same_thread=False))

    if kind == "redis":
        try:
            from langgraph.checkpoint.redis import RedisSaver
        except ImportError as error:
            raise RuntimeError(
                "The 'redis' extra is required for the redis checkpointer."
            ) from error

        from langswarm.config import settings

        saver = RedisSaver.from_conn_string(settings.redis_url)
        saver.setup()  # Redis 8.x includes the required JSON and Search modules
        return saver

    raise ValueError(
        f"Unknown checkpointer kind {kind!r}; expected 'memory', 'sqlite' or 'redis'."
    )
