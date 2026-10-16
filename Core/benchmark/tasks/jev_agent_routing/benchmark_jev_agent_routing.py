"""Agent task routing benchmark: Jev Choice local fallback vs golden labels."""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass

from Core.benchmark.jev_autolearn import run_golden_pass
from Core.benchmark.protocol import BenchmarkResult
from Core.benchmark.tasks.jev_agent_routing.cases import (
    AGENT_ROUTING_CASES,
    MAX_CHOICE_P50_MS,
    MIN_ROUTING_ACCURACY,
    REVIEW_CONFIDENCE_BELOW,
    SWARM_AGENT_CANDIDATES,
)
from swarm_sdk.core.jev_router import JevRouter

_WARMUP = 3
_LATENCY_ROUNDS = 20


@dataclass(frozen=True, slots=True)
class RoutingBenchmarkMetrics:
    """Measured routing quality for one run."""

    accuracy: float
    p50_ms: float
    p95_ms: float
    low_confidence_correct: int
    misroutes: tuple[tuple[str, str, str], ...]


def _evaluate_cases(router: JevRouter) -> RoutingBenchmarkMetrics:
    correct = 0
    low_confidence_correct = 0
    misroutes: list[tuple[str, str, str]] = []
    latencies: list[float] = []

    for goal, expected in AGENT_ROUTING_CASES:
        t0 = time.perf_counter()
        decision = router.evaluate_choice(goal, list(SWARM_AGENT_CANDIDATES))
        latencies.append((time.perf_counter() - t0) * 1000.0)
        if decision.selected_choice == expected:
            correct += 1
            if decision.confidence < REVIEW_CONFIDENCE_BELOW:
                low_confidence_correct += 1
        else:
            misroutes.append((goal[:80], expected, decision.selected_choice))

    latencies.sort()
    p50 = statistics.median(latencies)
    p95 = latencies[int(len(latencies) * 0.95)]
    accuracy = correct / len(AGENT_ROUTING_CASES)
    return RoutingBenchmarkMetrics(
        accuracy=accuracy,
        p50_ms=p50,
        p95_ms=p95,
        low_confidence_correct=low_confidence_correct,
        misroutes=tuple(misroutes),
    )


def _latency_only_p50(router: JevRouter) -> float:
    goal, _ = AGENT_ROUTING_CASES[0]
    for _ in range(_WARMUP):
        router.evaluate_choice(goal, list(SWARM_AGENT_CANDIDATES))
    samples = []
    for _ in range(_LATENCY_ROUNDS):
        t0 = time.perf_counter()
        router.evaluate_choice(goal, list(SWARM_AGENT_CANDIDATES))
        samples.append((time.perf_counter() - t0) * 1000.0)
    return statistics.median(samples)


def run_benchmark() -> BenchmarkResult:
    """Score local Choice routing against golden agent tasks."""
    router = JevRouter(endpoint=None, api_key="")
    metrics = _evaluate_cases(router)
    micro_p50 = _latency_only_p50(router)

    passed = (
        metrics.accuracy >= MIN_ROUTING_ACCURACY
        and metrics.p50_ms <= MAX_CHOICE_P50_MS
        and micro_p50 <= MAX_CHOICE_P50_MS
    )

    correct, total, _ = run_golden_pass(router)
    if correct != total:
        print(f"  autolearn: recorded misroutes ({correct}/{total} correct)")

    if not passed and metrics.misroutes:
        for goal, expected, got in metrics.misroutes[:5]:
            print(f"  misroute expected={expected} got={got}: {goal!r}")
            print("  rewind: MR2 (see Agents/_shared/JEV_REFLECT_AUTOLEARN.md)")

    print(
        f"  accuracy={metrics.accuracy:.2%} "
        f"p50={metrics.p50_ms:.2f}ms p95={metrics.p95_ms:.2f}ms "
        f"micro_p50={micro_p50:.2f}ms "
        f"low_conf_correct={metrics.low_confidence_correct}"
    )

    return BenchmarkResult(
        name="jev_agent_routing",
        p50_ms=metrics.p50_ms,
        passed=passed,
        accuracy=metrics.accuracy,
        p95_ms=metrics.p95_ms,
    )
