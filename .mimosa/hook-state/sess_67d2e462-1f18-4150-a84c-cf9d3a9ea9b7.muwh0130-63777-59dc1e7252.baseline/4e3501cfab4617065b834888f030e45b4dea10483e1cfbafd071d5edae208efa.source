"""CI-sized check for the cold-import benchmark: the improvement is real."""

from __future__ import annotations

import pytest
from benchmark.Tasks.cold_import import benchmark_cold_import
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


def test_paired_samples_follow_the_abba_cadence(monkeypatch: pytest.MonkeyPatch) -> None:
    """ABBA rotation keeps linear drift from landing on only one variant."""
    calls: list[str] = []

    class _Done:
        """Stand-in for ``subprocess.CompletedProcess`` carrying a fixed stdout."""

        stdout = "1.0\n"

    def fake_run(cmd: list[str], **_: object) -> _Done:
        calls.append(cmd[-1])
        return _Done()

    monkeypatch.setattr(benchmark_cold_import.subprocess, "run", fake_run)
    samples = benchmark_cold_import._paired_samples({"a": "A", "b": "B"}, rounds=2)
    assert calls == ["A", "B", "B", "A", "B", "A", "A", "B"]
    assert samples == {"a": [1.0] * 4, "b": [1.0] * 4}


def test_paired_samples_require_two_snippets() -> None:
    with pytest.raises(ValueError, match="two"):
        benchmark_cold_import._paired_samples({"a": "A"})
