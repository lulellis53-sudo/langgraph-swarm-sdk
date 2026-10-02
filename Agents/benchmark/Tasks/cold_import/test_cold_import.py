"""CI-sized check for the cold-import benchmark: the improvement is real."""

from __future__ import annotations

from benchmark.Tasks.cold_import.benchmark_cold_import import run


def test_cold_import_report_has_measured_improvement() -> None:
    report = run()
    assert [item["name"] for item in report["metrics"]] == ["cold_import_ms"]
    item = report["metrics"][0]
    assert item["baseline"] > 0.0
    assert item["current"] > 0.0
    assert item["current"] < item["baseline"]
    assert item["improvement_pct"] > 10.0
    assert report["mean_improvement_pct"] is not None
