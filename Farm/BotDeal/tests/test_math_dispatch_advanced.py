"""Tests for the extended math dispatch heuristics (operation, dtype, element count)."""

from __future__ import annotations

import pytest

from swarm_sdk.math.dispatch import classify_math_task
from swarm_sdk.math.types import MathProblem


@pytest.fixture(autouse=True)
def _clean_gpu_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SWARM_GPU_BACKEND", raising=False)
    monkeypatch.delenv("SWARM_OPENCL_MIN_ROWS", raising=False)


def test_cubic_operation_routes_to_gpu_at_smaller_size(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SWARM_GPU_BACKEND", "opencl")
    prob = MathProblem(
        problem_statement="Solve linear system",
        task_type="matrix",
        operation="solve",
        shape=(3000, 3000),
    )
    decision = classify_math_task(prob)
    assert decision.backend == "opencl"
    assert decision.gpu_enabled is True


def test_small_matmul_stays_on_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SWARM_GPU_BACKEND", "opencl")
    prob = MathProblem(
        problem_statement="Multiply small matrices",
        task_type="matrix",
        operation="matmul",
        shape=(1000, 1000),
    )
    decision = classify_math_task(prob)
    assert decision.backend == "numpy"


def test_large_matmul_routes_to_gpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SWARM_GPU_BACKEND", "opencl")
    prob = MathProblem(
        problem_statement="Multiply large matrices",
        task_type="matrix",
        operation="matmul",
        shape=(5000, 5000),
    )
    decision = classify_math_task(prob)
    assert decision.backend == "opencl"
    assert decision.gpu_enabled is True


def test_element_count_can_trigger_gpu_for_wide_matrices(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SWARM_GPU_BACKEND", "opencl")
    prob = MathProblem(
        problem_statement="Wide batch matmul",
        task_type="matrix",
        operation="matmul",
        shape=(2048, 8192),
    )
    decision = classify_math_task(prob)
    assert decision.backend == "opencl"
    assert decision.gpu_enabled is True


def test_float64_raises_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SWARM_GPU_BACKEND", "opencl")
    at_threshold = MathProblem(
        problem_statement="Solve linear system",
        task_type="matrix",
        operation="solve",
        shape=(2500, 8),
        dtype="float32",
    )
    assert classify_math_task(at_threshold).backend == "opencl"
    float64 = at_threshold.model_copy(update={"dtype": "float64"})
    # Float64 raises the effective threshold, so the same shape falls back.
    assert classify_math_task(float64).backend == "numpy"


def test_unknown_operation_uses_default_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SWARM_GPU_BACKEND", "opencl")
    prob = MathProblem(
        problem_statement="Generic matrix work",
        task_type="matrix",
        operation="unknown",
        shape=(8192, 64),
    )
    decision = classify_math_task(prob)
    assert decision.backend == "opencl"
