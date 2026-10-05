"""CI-sized checks for the Prediction performance benchmark (correctness, protocol, no timings)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from benchmark.Tasks.prediction_perf import benchmark_prediction_perf as bench
from benchmark.Tasks.prediction_perf.benchmark_prediction_perf import (
    WORKLOADS,
    BenchmarkCorrectnessError,
    Workload,
    check_correctness,
    main,
    make_panel,
    run,
    run_ab,
    time_calls,
)
from hypothesis import given, settings
from hypothesis import strategies as st
from Prediction import ForecastEngine

_VERDICTS = {"B_slower", "B_faster", "no_detectable_difference"}


@settings(max_examples=25, deadline=None)
@given(st.integers(1, 6), st.integers(30, 90))
def test_panel_shape_and_determinism(n_series: int, n_days: int) -> None:
    workload = Workload("t", n_series, n_days, 7)
    first = make_panel(workload, seed=3)
    assert len(first) == n_series * n_days
    assert first.equals(make_panel(workload, seed=3))
    assert not first.equals(make_panel(workload, seed=4))


def test_correctness_gate_passes_on_the_real_engine() -> None:
    result = check_correctness()
    assert result["rows"] == WORKLOADS["small"].n_series * WORKLOADS["small"].horizon
    assert result["mae"] <= bench.MAX_MAE


def test_gate_rejects_nan_forecasts(monkeypatch: pytest.MonkeyPatch) -> None:
    real_predict = ForecastEngine.predict

    def broken(self, horizon, **kwargs):  # noqa: ANN001, ANN003, ANN202
        frame = real_predict(self, horizon, **kwargs)
        frame["lgbm"] = np.nan
        return frame

    monkeypatch.setattr(ForecastEngine, "predict", broken)
    with pytest.raises(BenchmarkCorrectnessError, match="NaN"):
        check_correctness()


def test_gate_rejects_nondeterminism(monkeypatch: pytest.MonkeyPatch) -> None:
    real_predict = ForecastEngine.predict
    calls = {"n": 0}

    def drifting(self, horizon, **kwargs):  # noqa: ANN001, ANN003, ANN202
        calls["n"] += 1
        frame = real_predict(self, horizon, **kwargs)
        frame["lgbm"] = frame["lgbm"] + calls["n"] * 1e-6
        return frame

    monkeypatch.setattr(ForecastEngine, "predict", drifting)
    with pytest.raises(BenchmarkCorrectnessError, match="different forecasts"):
        check_correctness()


def test_gate_rejects_inaccurate_forecasts(monkeypatch: pytest.MonkeyPatch) -> None:
    real_predict = ForecastEngine.predict

    def biased(self, horizon, **kwargs):  # noqa: ANN001, ANN003, ANN202
        frame = real_predict(self, horizon, **kwargs)
        frame["lgbm"] = frame["lgbm"] + 50.0
        return frame

    monkeypatch.setattr(ForecastEngine, "predict", biased)
    with pytest.raises(BenchmarkCorrectnessError, match="MAE"):
        check_correctness()


def test_failed_observations_are_counted_not_timed() -> None:
    state = {"calls": 0}

    def flaky() -> None:
        state["calls"] += 1
        if state["calls"] == 3:  # call 1 is the warm-up; this is observation 2
            raise RuntimeError("boom")

    samples, errors = time_calls(flaky, 4, warmup=1)
    assert errors == 1
    assert len(samples) == 3
    assert all(sample >= 0.0 for sample in samples)


def test_ab_runs_abba_blocks_after_a_warmup_of_both_variants() -> None:
    order: list[str] = []
    report = run_ab(lambda: order.append("A"), lambda: order.append("B"), blocks=2, sessions=2)
    assert order[:2] == ["A", "B"]  # warm-up
    session = order[2:6], order[6:10], order[10:14], order[14:18]
    assert all(block == ["A", "B", "B", "A"] for block in session)
    assert len(report["sessions"]) == 2
    assert report["combined"] in _VERDICTS | {"inconclusive"}


def test_quick_run_report_schema_and_correctness_first() -> None:
    report = run(quick=True)
    assert report["task"] == "prediction_perf"
    assert report["correctness"]["mae"] <= bench.MAX_MAE
    names = [item["name"] for item in report["metrics"]]
    assert names == ["fit_p50_ms_small", "predict_p50_ms_small", "backtest_p50_ms_small"]
    for entry in report["suite"]["small"]["operations"].values():
        assert entry["errors"] == 0
        assert entry["summary"]["n"] == len(entry["samples_ms"]) > 0
        assert entry["summary"]["tail_reliable"] is False  # quick runs have far fewer than 100
        assert entry["peak_alloc_mib"] > 0
    ab = report["ab"]
    assert all(s["verdict"]["label"] in _VERDICTS for s in ab["sessions"])
    env = report["environment"]
    assert env["python"] and env["gc_policy"] and env["rss_peak_mib"] > 0
    json.dumps(report)  # fully serialisable


def test_cli_writes_json_report(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    assert main(["--quick", "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["task"] == "prediction_perf"
