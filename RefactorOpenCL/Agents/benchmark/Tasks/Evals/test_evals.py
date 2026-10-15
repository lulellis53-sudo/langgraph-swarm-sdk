"""CI-sized check: the ten cowork evals pass at caps 2/3/4 with real speedup."""

from __future__ import annotations

from benchmark.Tasks.Evals.benchmark_evals import run


def _by_name(report: dict, name: str) -> dict:
    return next(item for item in report["metrics"] if item["name"] == name)


def test_evals_completed_and_flow_verified() -> None:
    report = run()
    completed = _by_name(report, "evals_completed_pct")
    assert completed["current"] == 100.0
    caps = completed["detail"]["caps"]
    assert caps["2"]["peak_in_flight"] == 2
    assert caps["3"]["peak_in_flight"] == 3
    assert caps["4"]["peak_in_flight"] == 4


def test_parallel_waves_beat_serial_baseline() -> None:
    report = run()
    wall = _by_name(report, "parallel_wall_s")
    assert wall["baseline"] > 0.0
    assert wall["current"] < wall["baseline"]
    assert wall["improvement_pct"] > 10.0
    assert report["mean_improvement_pct"] is not None
