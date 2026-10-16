"""Minimal benchmark result schema."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    """Outcome of a single benchmark task run."""

    name: str
    p50_ms: float
    passed: bool
    accuracy: float | None = None
    p95_ms: float | None = None
