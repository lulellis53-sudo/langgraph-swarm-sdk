"""Tests for math problem models and contract types."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from swarm_sdk.math.types import (
    MathDispatchDecision,
    MathProblem,
    MathResult,
    VerificationResult,
)


def test_math_problem_defaults() -> None:
    prob = MathProblem(
        problem_statement="Solve 2x + 4 = 10",
        task_type="arithmetic",
    )
    assert prob.mode == "solve"
    assert prob.precision_tolerance == 1e-6
    assert prob.force_gpu is False


def test_math_dispatch_decision_roundtrip() -> None:
    decision = MathDispatchDecision(
        backend="opencl",
        gpu_enabled=True,
        selected_route={"name": "opencl_math", "provider": "local_gpu"},
        notes="Rows exceed threshold",
    )
    assert decision.backend == "opencl"
    assert decision.gpu_enabled is True
    data = decision.model_dump()
    assert data["backend"] == "opencl"


def test_math_result_serialization() -> None:
    res = MathResult(
        task_id="T1",
        status="done",
        mode="solve",
        selected_route={"name": "mistral:ministral-3-8b-latest", "provider": "mistral-2"},
        gpu_enabled=False,
        backend="llm",
        solution={
            "formulation": "Linear equation",
            "derivation": "2x = 6 => x = 3",
            "latex": "x = 3",
            "result": 3.0,
        },
        verification=VerificationResult(
            verified=True,
            method="sympy",
            script_snippet="assert 2*3 + 4 == 10",
            error_bound=0.0,
        ),
        notes="Exact solution",
    )
    assert res.verification is not None
    assert res.verification.verified is True
    assert res.solution["result"] == 3.0


def test_math_problem_rejects_bad_input() -> None:
    with pytest.raises(ValidationError):
        MathProblem(problem_statement="", task_type="arithmetic")
    with pytest.raises(ValidationError):
        MathProblem.model_validate({"problem_statement": "x", "task_type": "astrology"})
