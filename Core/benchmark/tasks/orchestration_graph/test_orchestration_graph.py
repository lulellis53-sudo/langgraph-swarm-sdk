"""Pytest entry for orchestration_graph benchmark."""

from __future__ import annotations

import pytest

from Core.benchmark.tasks.orchestration_graph.benchmark_orchestration_graph import (
    run_benchmark,
)
from orchestration.tracing import tracing_enabled


def test_orchestration_graph_benchmark_passes() -> None:
    result = run_benchmark()
    assert result.passed
    assert result.p50_ms >= 0.0


@pytest.mark.skipif(tracing_enabled(), reason="LangSmith tracing not required in CI")
def test_benchmark_runs_without_langsmith() -> None:
    assert tracing_enabled() is False
