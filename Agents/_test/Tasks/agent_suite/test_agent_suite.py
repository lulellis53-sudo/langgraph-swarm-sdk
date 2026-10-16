"""Catalog coverage, distribution properties, and instrument checks."""

from __future__ import annotations

import math
import statistics

import hypothesis.strategies as st
import pytest
from benchmark.Tasks.agent_suite.suite import (
    AGENTS_ROOT,
    TAIL_MIN_N,
    catalog,
    comparison_report,
    latency_distribution,
    main,
    measure,
)
from hypothesis import given, settings

from swarm_sdk.agents.manifest import AgentManifest, load_all_agent_manifests

_HYP = settings(max_examples=40, deadline=None)
_DURATIONS = st.lists(
    st.floats(min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False),
    min_size=2,
    max_size=40,
)


def test_catalog_covers_every_loaded_manifest_and_task() -> None:
    manifests = load_all_agent_manifests(AGENTS_ROOT)
    steps = catalog(manifests)

    assert {step.agent for step in steps} == set(manifests)
    for name, manifest in manifests.items():
        found = [step.task_id for step in steps if step.agent == name]
        expected = [task.id for task in manifest.tasks] or [""]
        assert found == expected


def test_tails_are_published_only_when_the_sample_supports_them() -> None:
    short = [float(value) for value in range(1, 31)]
    withheld = latency_distribution(short)

    assert withheld["n"] == 30
    assert withheld["p50_ms"] == statistics.median(short)
    assert withheld["median_ms"] == withheld["p50_ms"]
    assert withheld["p95_ms"] is None
    assert withheld["p99_ms"] is None
    assert withheld["tail_supported"] is False

    long = [float(value) for value in range(1, TAIL_MIN_N + 1)]
    published = latency_distribution(long)
    assert published["tail_supported"] is True
    assert published["p95_ms"] == long[math.ceil(0.95 * TAIL_MIN_N) - 1]
    assert published["p99_ms"] == long[math.ceil(0.99 * TAIL_MIN_N) - 1]


def test_distribution_rejects_a_single_sample() -> None:
    with pytest.raises(ValueError, match="samples"):
        latency_distribution([1.0])


async def test_measure_rejects_a_short_run() -> None:
    with pytest.raises(ValueError, match="samples"):
        await measure(samples=1)


@_HYP
@given(samples=_DURATIONS)
def test_distribution_matches_median_and_nearest_rank(samples: list[float]) -> None:
    stats = latency_distribution(samples)
    ordered = sorted(samples)
    count = len(ordered)

    assert stats["n"] == count
    assert stats["p50_ms"] == statistics.median(ordered)
    assert stats["median_ms"] == stats["p50_ms"]
    if stats["tail_supported"]:
        assert stats["p95_ms"] == ordered[math.ceil(0.95 * count) - 1]
        assert stats["p99_ms"] == ordered[math.ceil(0.99 * count) - 1]
        assert stats["p95_ms"] is not None
        assert stats["p99_ms"] is not None
        assert stats["p95_ms"] <= stats["p99_ms"]
    else:
        assert stats["p95_ms"] is None
        assert stats["p99_ms"] is None
    assert min(ordered) <= stats["p50_ms"] <= max(ordered)
    assert stats["mad_ms"] >= 0.0
    assert stats["tail_supported"] is (count >= TAIL_MIN_N)


@_HYP
@given(
    names=st.lists(
        st.from_regex(r"[A-Za-z][A-Za-z0-9]{0,8}", fullmatch=True),
        min_size=1,
        max_size=5,
        unique=True,
    ),
    task_count=st.integers(min_value=0, max_value=4),
)
def test_catalog_keeps_every_declared_task(names: list[str], task_count: int) -> None:
    manifests = {
        name: AgentManifest.model_validate(
            {
                "name": name,
                "role": "role",
                "tasks": [
                    {"id": f"t{index}", "description": f"do {index}"} for index in range(task_count)
                ],
            }
        )
        for name in names
    }

    steps = catalog(manifests)

    per_agent = task_count or 1
    assert len(steps) == len(names) * per_agent
    assert [step.agent for step in steps] == sorted(names * per_agent)
    for name in names:
        found = [step.task_id for step in steps if step.agent == name]
        expected = [f"t{index}" for index in range(task_count)] or [""]
        assert found == expected


async def test_solo_and_parallel_cover_the_catalog() -> None:
    report = await measure(warmup=1, samples=2)
    catalog_rows = report["catalog"]["tasks"]
    assert isinstance(catalog_rows, list)
    comparison = report["comparison"]
    assert comparison["claim"] == "none"
    assert comparison["runs"] == 1
    low_ms = comparison["paired_delta_ci95_low_ms"]
    high_ms = comparison["paired_delta_ci95_high_ms"]
    delta_ms = comparison["paired_delta_p50_ms"]
    assert isinstance(low_ms, float)
    assert isinstance(high_ms, float)
    assert isinstance(delta_ms, float)
    assert low_ms <= delta_ms <= high_ms
    assert report["peak_rss_bytes"] > 0
    assert report["failures"] == []

    for mode_name in ("solo", "parallel"):
        mode = report["modes"][mode_name]
        assert mode["n"] == 2
        assert mode["tail_supported"] is False
        assert mode["peak_in_flight"] >= 1
        assert mode["peak_in_flight"] <= 3
        assert len(mode["steps"]) == len(catalog_rows)
        for step in mode["steps"]:
            assert step["n"] == 2
            assert step["ok"] == 2
            assert step["blocked"] == 0
            assert step["error"] == 0
            assert step["prompt_tokens_p50"] > 0
            for key in ("p50_ms", "p95_ms", "p99_ms", "mad_ms", "cv_pct"):
                assert key in step
            assert step["p95_ms"] is None
            assert step["p99_ms"] is None
    assert report["modes"]["solo"]["peak_in_flight"] == 1
    assert TAIL_MIN_N == 100

    counted = len(catalog_rows) * 2 * 2
    instruments = report["instruments"]
    langchain = instruments["langchain"]
    prometheus = instruments["prometheus"]
    otel = instruments["opentelemetry"]
    python = instruments["python"]
    assert isinstance(langchain, dict)
    assert isinstance(prometheus, dict)
    assert isinstance(otel, dict)
    assert isinstance(python, dict)
    assert langchain["llm_starts"] == counted
    assert langchain["llm_ends"] == counted
    assert langchain["llm_errors"] == 0
    assert langchain["total_tokens"] > 0
    assert prometheus["available"] is True
    assert prometheus["steps_total"] == counted
    assert otel["available"] is True
    assert otel["span_count"] == counted + (2 * 2)
    assert otel["error_spans"] == 0
    cpu = python["cpu_ms"]
    traced = python["tracemalloc"]
    assert isinstance(cpu, dict)
    assert isinstance(traced, dict)
    assert cpu["solo"]["n"] == 2
    assert cpu["parallel"]["n"] == 2
    assert traced["peak_bytes"] > 0


def test_one_run_records_the_floor_without_claiming_a_win() -> None:
    report = comparison_report([10.0, 10.0, 10.0], [1.0, 1.0, 1.0], independent_runs=1)

    assert report["claim"] == "none"
    assert report["exceeds_two_dispersion"] is True
    assert report["paired_delta_p50_ms"] == -9.0
    assert report["paired_delta_ci95_low_ms"] == -9.0
    assert report["paired_delta_ci95_high_ms"] == -9.0


def test_a_second_run_claims_the_win_past_the_noise_floor() -> None:
    report = comparison_report([10.0, 10.0], [1.0, 1.0], independent_runs=2)
    assert report["claim"] == "win"
    assert report["exceeds_two_dispersion"] is True


def test_a_zero_delta_does_not_clear_a_zero_dispersion() -> None:
    report = comparison_report([5.0, 5.0], [5.0, 5.0], independent_runs=2)
    assert report["exceeds_two_dispersion"] is False
    assert report["claim"] == "none"


def run() -> None:
    """Entrypoint for ``python -m benchmark.run --task agent_suite``."""
    raise SystemExit(main([]))
