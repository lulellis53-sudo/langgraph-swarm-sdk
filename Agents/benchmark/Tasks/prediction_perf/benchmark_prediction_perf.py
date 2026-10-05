"""Performance benchmark for ``ForecastEngine`` following the Benchmark.md protocol.

Correctness is checked first and separately; then each operation is timed over many
independent observations (setup outside the timer, GC collected before each observation) and
reported as median/MAD/IQR/CV/P95/P99 with sample counts, peak allocations and RSS. A paired,
ABBA-interleaved A/B compares two feature configurations and only claims a difference when it
clears the noise floor in at least two independent sessions.

Run from the repository root with ``PYTHONHASHSEED=0 PYTHONPATH=.:Agents`` and
``python -m benchmark.Tasks.prediction_perf.benchmark_prediction_perf --out report.json``.
``--quick`` is CI-sized and makes no timing claims.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import platform
import resource
import subprocess
import sys
import time
import tracemalloc
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from benchmark.stats import (
    abba_schedule,
    block_deltas,
    combine_sessions,
    paired_verdict,
    summarize,
)
from Prediction import ForecastConfig, ForecastEngine

__all__ = [
    "BenchmarkCorrectnessError",
    "WORKLOADS",
    "Workload",
    "accuracy_metrics",
    "check_correctness",
    "host_noise",
    "import_cost_ms",
    "loglog_slope",
    "main",
    "make_panel",
    "run",
    "run_ab",
    "scaling_sweep",
    "throughput_per_s",
    "time_calls",
]

# Sanity bound on mean absolute error against the noiseless signal. Measured 2026-10-04 on the
# seeded panels: 0.350 (small), 0.203 (medium) with noise sd 0.3; 1.0 is a tripwire, not a target.
MAX_MAE = 1.0
_NS_PER_MS = 1_000_000.0
_MODEL_COLUMN = "lgbm"


class BenchmarkCorrectnessError(RuntimeError):
    """Raised when the engine's output is wrong, so timing it would be meaningless."""


@dataclass(frozen=True, slots=True)
class Workload:
    """Shape of one synthetic panel."""

    name: str
    n_series: int
    n_days: int
    horizon: int


WORKLOADS = {
    "small": Workload("small", n_series=5, n_days=120, horizon=14),
    "medium": Workload("medium", n_series=20, n_days=365, horizon=14),
}


def _signal(series: int, day: np.ndarray) -> np.ndarray:
    """Return the noiseless value of series ``series`` on integer ``day`` offsets."""
    return 10.0 + series + 0.01 * day + 3.0 * np.sin(2.0 * np.pi * day / 7.0)


def make_panel(workload: Workload, seed: int = 0) -> pd.DataFrame:
    """Build the seeded long-format panel (weekly seasonality, trend, Gaussian noise)."""
    rng = np.random.default_rng(seed)
    days = np.arange(workload.n_days)
    ds = pd.date_range("2024-01-01", periods=workload.n_days, freq="D")
    frames = [
        pd.DataFrame(
            {
                "unique_id": f"series-{i}",
                "ds": ds,
                "y": _signal(i, days) + rng.normal(0.0, 0.3, workload.n_days),
            }
        )
        for i in range(workload.n_series)
    ]
    return pd.concat(frames, ignore_index=True)


def _truth(workload: Workload) -> pd.DataFrame:
    """Return the noiseless signal over the forecast horizon."""
    days = np.arange(workload.n_days, workload.n_days + workload.horizon)
    ds = pd.date_range("2024-01-01", periods=workload.n_days + workload.horizon, freq="D")[
        workload.n_days :
    ]
    return pd.concat(
        [
            pd.DataFrame({"unique_id": f"series-{i}", "ds": ds, "truth": _signal(i, days)})
            for i in range(workload.n_series)
        ],
        ignore_index=True,
    )


def check_correctness(
    workload: Workload | None = None, config: ForecastConfig | None = None
) -> dict[str, Any]:
    """Verify determinism, output shape, finiteness and accuracy before any timing.

    Returns:
        The measured mean absolute error against the noiseless signal and the row count.

    Raises:
        BenchmarkCorrectnessError: If any check fails.
    """
    workload = workload or WORKLOADS["small"]
    frame = make_panel(workload)
    first = ForecastEngine(config).fit(frame).predict(workload.horizon)
    second = ForecastEngine(config).fit(frame).predict(workload.horizon)
    expected_rows = workload.n_series * workload.horizon
    if len(first) != expected_rows:
        raise BenchmarkCorrectnessError(f"expected {expected_rows} rows, got {len(first)}")
    if set(first["unique_id"]) != {f"series-{i}" for i in range(workload.n_series)}:
        raise BenchmarkCorrectnessError("forecast is missing a series")
    predictions = first[_MODEL_COLUMN].to_numpy()
    if not np.isfinite(predictions).all():
        raise BenchmarkCorrectnessError("forecast contains NaN or infinity")
    if not np.array_equal(predictions, second[_MODEL_COLUMN].to_numpy()):
        raise BenchmarkCorrectnessError("two identical fits gave different forecasts")
    merged = first.merge(_truth(workload), on=["unique_id", "ds"], how="inner")
    mae = float((merged[_MODEL_COLUMN] - merged["truth"]).abs().mean())
    if len(merged) != expected_rows or mae > MAX_MAE:
        raise BenchmarkCorrectnessError(f"forecast MAE {mae:.3f} exceeds {MAX_MAE}")
    return {"mae": round(mae, 4), "rows": len(first)}


def time_calls(
    op: Callable[[], object],
    n: int,
    *,
    warmup: int = 1,
    cpu_ms: list[float] | None = None,
) -> tuple[list[float], int]:
    """Time ``op`` ``n`` times (milliseconds), collecting garbage before each observation.

    Failed calls are counted, not timed, and never abort the run. When ``cpu_ms`` is given,
    the process CPU time of each successful call is appended to it.

    Returns:
        The successful observations in milliseconds and the number of failed calls.
    """
    for _ in range(warmup):
        op()
    samples: list[float] = []
    errors = 0
    for _ in range(n):
        gc.collect()
        cpu_start = time.process_time_ns()
        start = time.perf_counter_ns()
        try:
            op()
        except Exception:  # noqa: BLE001 - a failing observation is data, reported as an error count
            errors += 1
            continue
        wall = time.perf_counter_ns() - start
        samples.append(wall / _NS_PER_MS)
        if cpu_ms is not None:
            cpu_ms.append((time.process_time_ns() - cpu_start) / _NS_PER_MS)
    return samples, errors


def _peak_alloc_mb(op: Callable[[], object]) -> float:
    """Return the peak traced allocation of one ``op`` call in MiB (run outside the timer)."""
    gc.collect()
    tracemalloc.start()
    try:
        op()
        return tracemalloc.get_traced_memory()[1] / 2**20
    finally:
        tracemalloc.stop()


def _max_rss_mb() -> float:
    """Return the process peak RSS in MiB (``ru_maxrss`` is bytes on macOS, KiB elsewhere)."""
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return raw / 2**20 if sys.platform == "darwin" else raw / 1024


def throughput_per_s(median_ms: float, units: float) -> float:
    """Return ``units`` processed per second at the median latency ``median_ms``."""
    if median_ms <= 0:
        raise ValueError("median_ms must be positive")
    return units / (median_ms / 1000.0)


def loglog_slope(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Return the least-squares slope of ``log y`` on ``log x`` (the scaling exponent).

    Raises:
        ValueError: With fewer than two points, non-positive values, or a single distinct x.
    """
    if len(xs) < 2 or len(xs) != len(ys):
        raise ValueError("need at least two (x, y) pairs of equal length")
    if min(xs) <= 0 or min(ys) <= 0:
        raise ValueError("log-log slope needs strictly positive values")
    if len(set(xs)) < 2:
        raise ValueError("log-log slope needs at least two distinct x values")
    return float(np.polyfit(np.log(np.asarray(xs, float)), np.log(np.asarray(ys, float)), 1)[0])


def accuracy_metrics(predicted: np.ndarray, truth: np.ndarray) -> dict[str, float]:
    """Return MAE, RMSE, sMAPE (percent) and mean signed error (bias) of ``predicted``."""
    if predicted.shape != truth.shape:
        raise ValueError(f"shape mismatch: {predicted.shape} vs {truth.shape}")
    error = predicted - truth
    denominator = np.abs(predicted) + np.abs(truth)
    return {
        "mae": float(np.abs(error).mean()),
        "rmse": float(np.sqrt((error**2).mean())),
        "smape_pct": float(100.0 * (2.0 * np.abs(error) / np.maximum(denominator, 1e-9)).mean()),
        "bias": float(error.mean()),
    }


def _accuracy(names: Sequence[str]) -> dict[str, Any]:
    """Score held-out forecasts against the noiseless signal and summarise the rolling backtest."""
    report: dict[str, Any] = {}
    for name in names:
        workload = WORKLOADS[name]
        frame = make_panel(workload)
        forecast = ForecastEngine().fit(frame).predict(workload.horizon)
        merged = forecast.merge(_truth(workload), on=["unique_id", "ds"], how="inner")
        backtest = ForecastEngine().backtest(frame, horizon=workload.horizon, n_windows=3)
        report[name] = {
            "holdout": accuracy_metrics(
                merged[_MODEL_COLUMN].to_numpy(), merged["truth"].to_numpy()
            ),
            "backtest_mean": {
                column: float(backtest[column].mean()) for column in ("mae", "rmse", "smape")
            },
        }
    return report


def scaling_sweep(
    sizes: Sequence[int] = (5, 10, 20, 40),
    *,
    n_days: int = 180,
    horizon: int = 14,
    observations: int = 10,
) -> dict[str, Any]:
    """Time ``fit`` as the number of series grows and fit the scaling exponent."""
    points: list[dict[str, Any]] = []
    for n_series in sizes:
        frame = make_panel(Workload("sweep", n_series, n_days, horizon))
        samples, _ = time_calls(lambda frame=frame: ForecastEngine().fit(frame), observations)
        median = summarize(samples).median
        rows = n_series * n_days
        points.append(
            {
                "n_series": n_series,
                "rows": rows,
                "fit_median_ms": round(median, 3),
                "us_per_row": round(median * 1000.0 / rows, 3),
            }
        )
    exponent = loglog_slope([p["n_series"] for p in points], [p["fit_median_ms"] for p in points])
    return {"n_days": n_days, "points": points, "fit_scaling_exponent": round(exponent, 3)}


def import_cost_ms(runs: int = 5) -> dict[str, Any]:
    """Time ``import Prediction`` plus engine construction in fresh interpreter processes."""
    root = Path(__file__).resolve().parents[4]
    env = {**os.environ, "PYTHONPATH": str(root)}
    code = "import Prediction; Prediction.ForecastEngine()"
    timings: list[float] = []
    for _ in range(runs):
        start = time.perf_counter_ns()
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"import probe failed: {result.stderr.strip()[-200:]}")
        timings.append((time.perf_counter_ns() - start) / _NS_PER_MS)
    summary = summarize(timings)
    return {"runs": runs, "median_ms": summary.median, "min_ms": summary.min, "max_ms": summary.max}


def host_noise(observations: int = 200) -> dict[str, Any]:
    """Characterise measurement noise: a fixed CPU workload's spread and the clock-call cost."""

    def fixed_work() -> int:
        return sum(i * i for i in range(20_000))

    samples, _ = time_calls(fixed_work, observations)
    summary = summarize(samples)
    ticks = [time.perf_counter_ns() for _ in range(2001)]
    clock_call_ns = float(np.median(np.diff(ticks)))
    return {
        "n": summary.n,
        "median_ms": summary.median,
        "mad_pct_of_median": 100.0 * summary.mad / summary.median if summary.median else 0.0,
        "cv_pct": summary.cv_pct,
        "clock_call_ns": clock_call_ns,
    }


def _operations(
    workload: Workload, config: ForecastConfig | None
) -> dict[str, Callable[[], object]]:
    """Build the timed operations; data generation and the fitted model are set up here."""
    frame = make_panel(workload)
    fitted = ForecastEngine(config).fit(frame)
    return {
        "fit": lambda: ForecastEngine(config).fit(frame),
        "predict": lambda: fitted.predict(workload.horizon),
        "backtest": lambda: ForecastEngine(config).backtest(
            frame, horizon=workload.horizon, n_windows=3
        ),
    }


def run_ab(
    op_a: Callable[[], object],
    op_b: Callable[[], object],
    *,
    blocks: int,
    sessions: int,
) -> dict[str, Any]:
    """Compare two operations with ABBA interleaving over independent sessions.

    Each session warms both variants, then times ``A B B A`` blocks; the verdict uses the
    paired per-block deltas and the noise-floor rule, and sessions must agree to claim a win.
    """
    ops = {"A": op_a, "B": op_b}
    op_a()
    op_b()
    session_results: list[dict[str, Any]] = []
    for session in range(sessions):
        records: list[tuple[str, float]] = []
        for variant in abba_schedule(blocks):
            gc.collect()
            start = time.perf_counter_ns()
            ops[variant]()
            records.append((variant, (time.perf_counter_ns() - start) / _NS_PER_MS))
        verdict = paired_verdict(block_deltas(records), seed=session)
        session_results.append(
            {
                "verdict": asdict(verdict),
                "A_ms": asdict(summarize([v for k, v in records if k == "A"])),
                "B_ms": asdict(summarize([v for k, v in records if k == "B"])),
            }
        )
    return {
        "blocks_per_session": blocks,
        "sessions": session_results,
        "combined": combine_sessions([s["verdict"]["label"] for s in session_results]),
    }


def environment() -> dict[str, Any]:
    """Describe the host, interpreter, library versions and measurement policy."""

    def version(name: str) -> str:
        try:
            return metadata.version(name)
        except metadata.PackageNotFoundError:
            return "not installed"

    try:
        commit: str | None = (
            subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            ).stdout.strip()
            or None
        )
    except OSError, subprocess.TimeoutExpired:
        commit = None
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "load_average_1m": round(os.getloadavg()[0], 2),
        "pythonhashseed": os.environ.get("PYTHONHASHSEED", "unset"),
        "packages": {name: version(name) for name in ("numpy", "pandas", "lightgbm", "mlforecast")},
        "git_commit": commit,
        "gc_policy": "enabled; gc.collect() before every observation, outside the timer",
        "engine_threads": 1,
    }


def _suite(
    names: Sequence[str], observations: dict[str, int], config: ForecastConfig | None
) -> dict[str, Any]:
    """Time every operation of every named workload and summarise the observations."""
    report: dict[str, Any] = {}
    for name in names:
        workload = WORKLOADS[name]
        entries: dict[str, Any] = {}
        input_rows = workload.n_series * workload.n_days
        output_rows = workload.n_series * workload.horizon
        rows_per_call = {"fit": input_rows, "predict": output_rows, "backtest": input_rows}
        for op_name, op in _operations(workload, config).items():
            cpu: list[float] = []
            rss_before = _max_rss_mb()
            samples, errors = time_calls(op, observations[op_name], cpu_ms=cpu)
            rss_growth = max(0.0, _max_rss_mb() - rss_before)
            summary = summarize(samples) if samples else None
            entry: dict[str, Any] = {
                "unit": "ms",
                "errors": errors,
                "summary": asdict(summary) if summary else None,
                "peak_alloc_mib": round(_peak_alloc_mb(op), 2),
                "rss_growth_mib": round(rss_growth, 2),
                "samples_ms": [round(s, 4) for s in samples],
            }
            if summary:
                cpu_summary = summarize(cpu)
                entry |= {
                    "min_ms": summary.min,
                    "throughput": {
                        "ops_per_s": throughput_per_s(summary.median, 1),
                        "rows_per_s": throughput_per_s(summary.median, rows_per_call[op_name]),
                    },
                    "cpu_ms": asdict(cpu_summary),
                    "cpu_wall_ratio": cpu_summary.median / summary.median,
                }
            entries[op_name] = entry
        report[name] = {"workload": asdict(workload), "operations": entries}
    return report


def run(
    *,
    quick: bool = False,
    workloads: Sequence[str] | None = None,
    observations: dict[str, int] | None = None,
    ab_blocks: int | None = None,
    sessions: int | None = None,
) -> dict[str, Any]:
    """Run correctness, the timing suite and the A/B; ``quick`` is CI-sized (no timing claims)."""
    names = list(workloads or (["small"] if quick else ["small", "medium"]))
    obs = observations or (
        {"fit": 3, "predict": 5, "backtest": 2}
        if quick
        else {"fit": 30, "predict": 200, "backtest": 15}
    )
    blocks = ab_blocks or (2 if quick else 15)
    n_sessions = sessions or 2
    correctness = check_correctness()
    suite = _suite(names, obs, None)
    accuracy = _accuracy(names)
    scaling = (
        scaling_sweep((2, 4), n_days=60, horizon=7, observations=2) if quick else scaling_sweep()
    )
    import_cost = import_cost_ms(runs=2 if quick else 5)
    noise = host_noise(observations=30 if quick else 200)
    ab_workload = WORKLOADS[names[-1]]
    ab_frame = make_panel(ab_workload)
    config_b = ForecastConfig(lags=(1, 7, 14))
    ab = run_ab(
        lambda: ForecastEngine().fit(ab_frame),
        lambda: ForecastEngine(config_b).fit(ab_frame),
        blocks=blocks,
        sessions=n_sessions,
    )
    ab["description"] = "fit: A lags=(1, 7) vs B lags=(1, 7, 14)"
    ab["workload"] = ab_workload.name
    metrics = [
        {
            "name": f"{op}_p50_ms_{name}",
            "current": round(entry["summary"]["median"], 4),
            "higher_is_better": False,
        }
        for name, block in suite.items()
        for op, entry in block["operations"].items()
        if entry["summary"]
    ]
    metrics += [
        {
            "name": f"{op}_rows_per_s_{name}",
            "current": round(entry["throughput"]["rows_per_s"], 1),
            "higher_is_better": True,
        }
        for name, block in suite.items()
        for op, entry in block["operations"].items()
        if entry["summary"]
    ]
    metrics += [
        {
            "name": f"holdout_mae_{name}",
            "current": round(a["holdout"]["mae"], 4),
            "higher_is_better": False,
        }
        for name, a in accuracy.items()
    ]
    metrics += [
        {
            "name": "fit_scaling_exponent",
            "current": scaling["fit_scaling_exponent"],
            "higher_is_better": False,
        },
        {
            "name": "import_cost_ms",
            "current": round(import_cost["median_ms"], 1),
            "higher_is_better": False,
        },
    ]
    return {
        "task": "prediction_perf",
        "quick": quick,
        "metrics": metrics,
        "correctness": correctness,
        "environment": {
            **environment(),
            "rss_peak_mib": round(_max_rss_mb(), 1),
            "load_average_1m_end": round(os.getloadavg()[0], 2),
        },
        "suite": suite,
        "accuracy": accuracy,
        "scaling": scaling,
        "import_cost": import_cost,
        "host_noise": noise,
        "ab": ab,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run the benchmark from the command line and optionally save the raw JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--workloads", nargs="+", choices=sorted(WORKLOADS))
    parser.add_argument("--obs-fit", type=int)
    parser.add_argument("--obs-predict", type=int)
    parser.add_argument("--obs-backtest", type=int)
    parser.add_argument("--ab-blocks", type=int)
    parser.add_argument("--sessions", type=int)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    observations = None
    if args.obs_fit or args.obs_predict or args.obs_backtest:
        observations = {
            "fit": args.obs_fit or 30,
            "predict": args.obs_predict or 200,
            "backtest": args.obs_backtest or 15,
        }
    report = run(
        quick=args.quick,
        workloads=args.workloads,
        observations=observations,
        ab_blocks=args.ab_blocks,
        sessions=args.sessions,
    )
    text = json.dumps(report, indent=2)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
