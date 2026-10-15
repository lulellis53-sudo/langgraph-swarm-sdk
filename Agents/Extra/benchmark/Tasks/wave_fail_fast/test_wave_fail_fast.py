"""CI-sized check for the fail-fast benchmark: cancellation actually saves work."""

from __future__ import annotations

from benchmark.Tasks.wave_fail_fast.benchmark_wave_fail_fast import run


def _by_name(report: dict, name: str) -> dict:
    return next(item for item in report["metrics"] if item["name"] == name)


def test_fail_fast_report_has_both_metrics() -> None:
    report = run()
    assert {item["name"] for item in report["metrics"]} == {
        "wave_tokens_burned",
        "siblings_still_running",
    }
    assert report["mean_improvement_pct"] is not None


def test_fail_fast_burns_fewer_tokens_and_leaves_no_zombies() -> None:
    report = run()
    tokens = _by_name(report, "wave_tokens_burned")
    assert tokens["baseline"] > 0.0
    assert tokens["current"] < tokens["baseline"]
    assert tokens["improvement_pct"] > 25.0
    siblings = _by_name(report, "siblings_still_running")
    assert siblings["baseline"] > 0.0
    assert siblings["current"] == 0.0
