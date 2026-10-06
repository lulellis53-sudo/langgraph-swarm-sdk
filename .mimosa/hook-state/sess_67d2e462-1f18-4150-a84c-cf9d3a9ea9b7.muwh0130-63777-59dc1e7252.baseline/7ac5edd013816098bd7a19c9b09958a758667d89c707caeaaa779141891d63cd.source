"""CI-sized smoke test: every case runs and reports a well-formed result (no timing assertions)."""

from __future__ import annotations

import json
import subprocess
import sys

from benchmark.Tasks.freethread_matrix import bench_cases, run_matrix


def test_quick_run_reports_every_case_without_errors() -> None:
    report = bench_cases.run(quick=True)
    assert set(report["cases"]) == set(bench_cases.CASES)
    assert all("error" not in case for case in report["cases"].values())
    cpu = report["cases"]["threads_cpu"]
    assert set(cpu["seconds"]) == {"1", "2", "4", "6"} and cpu["speedup"]["1"] == 1.0


def test_json_output_is_one_parseable_object() -> None:
    out = subprocess.run(
        [sys.executable, bench_cases.__file__, "--json", "--quick", "--case", "numba"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert json.loads(out)["cases"].keys() == {"numba"}


def test_sentinel_case_matches_the_interpreter() -> None:
    result = bench_cases.case_sentinel(quick=True)
    if sys.version_info >= (3, 15):
        assert result["copy_keeps_identity"] == {"sentinel": True, "object()": False}
    else:
        assert "skipped" in result


def test_table_marks_missing_interpreters_and_skipped_cases() -> None:
    text = run_matrix.table({"x": {"error": "not found"}})
    assert "not found" in text and text.count("|") > 8


def test_load_above_the_core_count_marks_a_run_noisy(monkeypatch) -> None:
    monkeypatch.setattr(run_matrix.os, "cpu_count", lambda: 8)
    assert run_matrix.noisy({"loadavg_1m_start": 2.0, "loadavg_1m_end": 9.5})
    assert not run_matrix.noisy({"loadavg_1m_start": 2.0, "loadavg_1m_end": 3.0})
    rep = {"gil_enabled": False, "loadavg_1m_start": 40, "loadavg_1m_end": 41, "cases": {}}
    assert "**NOISY**" in run_matrix.table({"3.15t": rep})


def test_wait_idle_returns_immediately_when_the_machine_is_quiet(monkeypatch) -> None:
    monkeypatch.setattr(run_matrix.os, "getloadavg", lambda: (0.5, 0.5, 0.5))
    assert run_matrix.wait_idle(6, 30) == 0.5
