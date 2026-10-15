"""Benchmark metric helpers."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import polars as pl


@dataclass
class RunMetrics:
    task: str
    tokens: int = 0
    latency_ms: float = 0.0
    cache_hit: bool = False
    recall_at_k: float | None = None
    extra: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        out: dict[str, object] = {
            "task": self.task,
            "tokens": self.tokens,
            "latency_ms": self.latency_ms,
            "cache_hit": self.cache_hit,
        }
        if self.recall_at_k is not None:
            out["recall_at_k"] = self.recall_at_k
        out.update(self.extra)
        return out


class Timer:
    def __init__(self) -> None:
        self._start = 0.0

    def __enter__(self) -> Timer:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args: object) -> None:
        self.elapsed_ms = (time.perf_counter() - self._start) * 1000.0


def metrics_frame(rows: list[RunMetrics]) -> pl.DataFrame:
    return pl.DataFrame([row.to_dict() for row in rows])
