"""Checkpointer factory: durable SQLite when a path is configured, else in-memory."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from langgraph.checkpoint.base import BaseCheckpointSaver


def open_checkpointer(path: str | None) -> BaseCheckpointSaver:
    """Open the LangGraph checkpointer for swarm threads.

    Args:
        path: SQLite file path, or ``None`` for a process-local in-memory saver.

    Returns:
        A ``SqliteSaver`` (parent directories created) or an ``InMemorySaver``.
    """
    if path is None:
        from langgraph.checkpoint.memory import InMemorySaver

        return InMemorySaver()
    from langgraph.checkpoint.sqlite import SqliteSaver

    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    # The graph runs in worker threads (offload); SqliteSaver serialises writes with its own lock.
    return SqliteSaver(sqlite3.connect(target, check_same_thread=False))


__all__ = ["open_checkpointer"]
