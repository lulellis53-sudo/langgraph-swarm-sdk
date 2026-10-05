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
    accuracy_metrics,
    check_correctness,
    host_noise,
    import_cost_ms,
    loglog_slope,
    main,
    make_panel,
    run,
    run_ab,
    scaling_sweep,
    throughput_per_s,
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
    assert names[:3] == ["fit_p50_ms_small", "predict_p50_ms_small", "backtest_p50_ms_small"]
    assert {
        "fit_rows_per_s_small",
        "holdout_mae_small",
        "fit_scaling_exponent",
        "import_cost_ms",
    } <= set(names)
    for entry in report["suite"]["small"]["operations"].values():
        assert entry["errors"] == 0
        assert entry["throughput"]["ops_per_s"] > 0
        assert entry["throughput"]["rows_per_s"] > 0
        assert entry["cpu_ms"]["median"] >= 0
        assert entry["cpu_wall_ratio"] > 0
        assert entry["rss_growth_mib"] >= 0
        assert entry["min_ms"] == entry["summary"]["min"]
        assert entry["summary"]["n"] == len(entry["samples_ms"]) > 0
        assert entry["summary"]["tail_reliable"] is False  # quick runs have far fewer than 100
        assert entry["peak_alloc_mib"] > 0
    ab = report["ab"]
    assert all(s["verdict"]["label"] in _VERDICTS for s in ab["sessions"])
    env = report["environment"]
    assert env["python"] and env["gc_policy"] and env["rss_peak_mib"] > 0
    accuracy = report["accuracy"]["small"]
    assert accuracy["holdout"]["mae"] <= bench.MAX_MAE
    assert {"mae", "rmse", "smape_pct", "bias"} <= accuracy["holdout"].keys()
    assert {"mae", "rmse", "smape"} <= accuracy["backtest_mean"].keys()
    assert len(report["scaling"]["points"]) >= 2
    assert report["import_cost"]["median_ms"] > 0
    assert report["host_noise"]["n"] > 0
    assert env["load_average_1m_end"] >= 0
    json.dumps(report)  # fully serialisable


def test_cli_writes_json_report(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    assert main(["--quick", "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["task"] == "prediction_perf"


def test_throughput_is_units_per_second_of_the_median() -> None:
    assert throughput_per_s(median_ms=250.0, units=1000) == pytest.approx(4000.0)
    with pytest.raises(ValueError, match="positive"):
        throughput_per_s(median_ms=0.0, units=10)


def test_loglog_slope_recovers_the_scaling_exponent() -> None:
    xs = [5, 10, 20, 40]
    assert loglog_slope(xs, [3.0 * x for x in xs]) == pytest.approx(1.0)
    assert loglog_slope(xs, [x**2 for x in xs]) == pytest.approx(2.0)
    assert loglog_slope(xs, [7.0] * 4) == pytest.approx(0.0)


@pytest.mark.parametrize(("xs", "ys"), [([1], [1.0]), ([1, 2], [1.0, 0.0]), ([1, 1], [1.0, 2.0])])
def test_loglog_slope_rejects_degenerate_input(xs: list[int], ys: list[float]) -> None:
    with pytest.raises(ValueError):
        loglog_slope(xs, ys)


def test_accuracy_metrics_on_known_values() -> None:
    metrics = accuracy_metrics(np.array([11.0, 9.0, 12.0]), np.array([10.0, 10.0, 10.0]))
    assert metrics["mae"] == pytest.approx(4 / 3)
    assert metrics["rmse"] == pytest.approx(((1 + 1 + 4) / 3) ** 0.5)
    assert metrics["bias"] == pytest.approx(2 / 3)
    expected_smape = 100 * np.mean([2 * 1 / 21, 2 * 1 / 19, 2 * 2 / 22])
    assert metrics["smape_pct"] == pytest.approx(expected_smape)


def test_accuracy_metrics_reject_mismatched_shapes() -> None:
    with pytest.raises(ValueError, match="shape"):
        accuracy_metrics(np.zeros(3), np.zeros(4))


def test_time_calls_can_report_cpu_time_per_observation() -> None:
    cpu: list[float] = []
    samples, _ = time_calls(lambda: sum(range(20_000)), 5, warmup=1, cpu_ms=cpu)
    assert len(cpu) == len(samples) == 5
    assert all(value >= 0.0 for value in cpu)


def test_scaling_sweep_reports_each_size_and_an_exponent() -> None:
    result = scaling_sweep(sizes=(2, 4), n_days=60, horizon=7, observations=2)
    assert [row["n_series"] for row in result["points"]] == [2, 4]
    assert all(row["rows"] == row["n_series"] * 60 for row in result["points"])
    assert all(row["fit_median_ms"] > 0 and row["us_per_row"] > 0 for row in result["points"])
    assert isinstance(result["fit_scaling_exponent"], float)


def test_import_cost_is_measured_in_fresh_processes() -> None:
    result = import_cost_ms(runs=2)
    assert result["runs"] == 2
    assert result["median_ms"] > 0
    assert result["median_ms"] <= result["max_ms"]


def test_host_noise_reports_a_calibration_distribution() -> None:
    noise = host_noise(observations=30)
    assert noise["n"] == 30
    assert noise["median_ms"] > 0
    assert noise["cv_pct"] >= 0
    assert noise["clock_call_ns"] > 0
