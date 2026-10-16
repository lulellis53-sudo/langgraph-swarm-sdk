"""Pytest entry for jev_agent_routing benchmark."""

from __future__ import annotations

from Core.benchmark.tasks.jev_agent_routing.benchmark_jev_agent_routing import (
    run_benchmark,
)
from Core.benchmark.tasks.jev_agent_routing.cases import (
    AGENT_ROUTING_CASES,
    MIN_ROUTING_ACCURACY,
)


def test_jev_agent_routing_benchmark_passes() -> None:
    result = run_benchmark()
    assert result.passed
    assert result.accuracy is not None
    assert result.accuracy >= MIN_ROUTING_ACCURACY
    assert len(AGENT_ROUTING_CASES) >= 10
