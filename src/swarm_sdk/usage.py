"""Token-usage rollups with Polars."""

import polars as pl


class UsageLog:
    def __init__(self) -> None:
        self._rows: list[dict[str, object]] = []

    def add(self, agent: str, tokens: int, cached: bool) -> None:
        self._rows.append({"agent": agent, "tokens": tokens, "cached": cached})

    def summary(self) -> list[dict[str, object]]:
        if not self._rows:
            return []
        frame = pl.DataFrame(self._rows)
        grouped = frame.group_by("agent").agg(pl.col("tokens").sum().alias("tokens"))
        return grouped.sort("agent").to_dicts()
