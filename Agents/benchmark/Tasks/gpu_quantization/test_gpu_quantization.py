"""CI-sized checks for the quantization benchmark (NumPy path, no OpenCL needed)."""

from __future__ import annotations

from benchmark.Tasks.gpu_quantization.benchmark_gpu_quantization import run


def test_quantization_benchmark_reports_all_modes() -> None:
    report = run(rows=200, dim=64, queries=5, k=5)
    modes = {(p["backend"], p["quantize"]) for p in report["profiles"]}
    assert ("numpy", "none") in modes
    assert ("numpy", "int8") in modes
    assert ("numpy", "binary") in modes
    none = next(p for p in report["profiles"] if p["quantize"] == "none")
    binary = next(p for p in report["profiles"] if p["quantize"] == "binary")
    assert none["recall_at_k"] == 1.0
    assert binary["resident_vector_bytes"] < none["resident_vector_bytes"]


def test_quantization_benchmark_names_smallest_accurate_mode() -> None:
    report = run(rows=200, dim=64, queries=5, k=5)
    best = report["best_by_recall"]
    assert best is not None
    assert best["recall_at_k"] >= 0.9
    qualifying = [
        p
        for p in report["profiles"]
        if p["recall_at_k"] >= 0.9  # type: ignore[union-attr]
    ]
    smallest = min(qualifying, key=lambda p: p["resident_vector_bytes"])
    assert best["quantize"] == smallest["quantize"]


def test_quantization_benchmark_restores_threshold(monkeypatch) -> None:
    import os

    monkeypatch.setenv("SWARM_OPENCL_MIN_ROWS", "123")
    run(rows=64, dim=32, queries=3, k=3)
    assert os.environ["SWARM_OPENCL_MIN_ROWS"] == "123"
