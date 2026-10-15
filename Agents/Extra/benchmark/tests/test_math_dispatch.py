"""Tests for hardware-aware math dispatch and crossover heuristics."""

from __future__ import annotations

import pytest
from swarm_sdk.math.dispatch import classify_math_task
from swarm_sdk.math.types import MathProblem


@pytest.fixture(autouse=True)
def _clean_gpu_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SWARM_GPU_BACKEND", raising=False)
    monkeypatch.delenv("SWARM_OPENCL_MIN_ROWS", raising=False)


def test_small_matrix_routes_to_numpy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SWARM_GPU_BACKEND", "opencl")
    prob = MathProblem(
        problem_statement="Multiply 256x256 matrices",
        task_type="matrix",
        shape=(256, 256),
    )
    decision = classify_math_task(prob)
    assert decision.backend == "numpy"
    assert decision.gpu_enabled is False


def test_large_matrix_routes_to_gpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SWARM_GPU_BACKEND", "opencl")
    prob = MathProblem(
        problem_statement="Multiply 10000x1024 matrix",
        task_type="matrix",
        shape=(10000, 1024),
    )
    decision = classify_math_task(prob)
    assert decision.backend == "opencl"
    assert decision.gpu_enabled is True


def test_cached_buffer_routes_to_gpu_even_for_medium_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SWARM_GPU_BACKEND", "opencl")
    prob = MathProblem(
        problem_statement="Search resident store",
        task_type="vector",
        shape=(1024, 768),
    )
    decision = classify_math_task(prob, has_cache_key=True)
    assert decision.backend == "opencl"
    assert decision.gpu_enabled is True


def test_formal_proof_routes_to_high_reasoning() -> None:
    prob = MathProblem(
        problem_statement="Prove that the square root of 2 is irrational",
        task_type="proof",
    )
    decision = classify_math_task(prob)
    assert decision.backend == "llm"
    assert decision.selected_route["provider"] in {"claude-code", "google", "codex", "zai"}
    assert decision.think_level in {"high", "xhigh"}


def test_crossover_boundary_is_inclusive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SWARM_GPU_BACKEND", "opencl")
    below = MathProblem(problem_statement="m", task_type="matrix", shape=(8191, 64))
    at = MathProblem(problem_statement="m", task_type="matrix", shape=(8192, 64))
    assert classify_math_task(below).backend == "numpy"
    assert classify_math_task(at).backend == "opencl"


def test_large_matrix_without_gpu_backend_stays_on_cpu() -> None:
    prob = MathProblem(problem_statement="m", task_type="matrix", shape=(100000, 64))
    decision = classify_math_task(prob)
    assert decision.backend == "numpy"
    assert decision.gpu_enabled is False


def test_force_gpu_without_env_uses_opencl() -> None:
    prob = MathProblem(problem_statement="m", task_type="vector", shape=(9000, 8), force_gpu=True)
    assert classify_math_task(prob).backend == "opencl"


@pytest.mark.parametrize("name", ["metal", "vulkan", "molten"])
def test_metal_family_backends_map_to_molten(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv("SWARM_GPU_BACKEND", name)
    prob = MathProblem(problem_statement="m", task_type="matrix", shape=(9000, 8))
    assert classify_math_task(prob).backend == "molten"


def test_unknown_gpu_backend_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SWARM_GPU_BACKEND", "cuda")
    prob = MathProblem(problem_statement="m", task_type="matrix", shape=(9000, 8))
    decision = classify_math_task(prob)
    assert decision.backend == "numpy"
    assert decision.gpu_enabled is False


@pytest.mark.parametrize("shape", [None, (), (0,), (0, 0), (0, 768)])
def test_empty_or_zero_shapes_do_not_crash(monkeypatch: pytest.MonkeyPatch, shape) -> None:
    monkeypatch.setenv("SWARM_GPU_BACKEND", "opencl")
    prob = MathProblem(problem_statement="empty", task_type="vector", shape=shape)
    decision = classify_math_task(prob)
    assert decision.backend == "numpy"
    assert decision.gpu_enabled is False


@pytest.mark.parametrize(
    ("task_type", "provider", "level"),
    [
        ("arithmetic", "moonshot", "low"),
        ("stats", "openai", "medium"),
        ("calculus", None, "high"),
        ("optimization", None, "high"),
    ],
)
def test_llm_routes_by_task_type(task_type: str, provider: str | None, level: str) -> None:
    prob = MathProblem.model_validate({"problem_statement": "p", "task_type": task_type})
    decision = classify_math_task(prob)
    assert decision.backend == "llm"
    assert decision.think_level == level
    if provider is not None:
        assert decision.selected_route["provider"] == provider
