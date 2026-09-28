"""Token-usage rollups with Polars."""

from __future__ import annotations

import polars as pl


class UsageLog:
    """Accumulate per-agent token rows and summarize with Polars."""

    def __init__(self) -> None:
        """Create an empty usage log."""
        self._rows: list[dict[str, object]] = []

    def add(self, agent: str, tokens: int, cached: bool) -> None:
        """Record one usage event.

        Args:
            agent: Agent or subsystem name (e.g. ``"coder"``, ``"cache"``).
            tokens: Tokens charged to that agent for this event.
            cached: Whether the response came from the semantic cache.
        """
        self._rows.append({"agent": agent, "tokens": tokens, "cached": cached})

    def summary(self) -> list[dict[str, object]]:
        """Sum tokens per agent, sorted by agent name.

        Returns:
            List of ``{"agent": str, "tokens": int}`` dicts, or ``[]`` when empty.
        """
        if not self._rows:
            return []
        frame = pl.DataFrame(self._rows)
        grouped = frame.group_by("agent").agg(pl.col("tokens").sum().alias("tokens"))
        return grouped.sort("agent").to_dicts()
