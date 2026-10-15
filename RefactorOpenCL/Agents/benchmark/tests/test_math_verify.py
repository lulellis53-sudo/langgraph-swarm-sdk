"""Tests for computational mathematical verification."""

from __future__ import annotations

import pytest
from swarm_sdk.math.verify import verify_math_solution


def test_verify_symbolic_solution() -> None:
    res = verify_math_solution(
        claim="Derivative of x^2 is 2x",
        expected="2*x",
        script="import sympy as sp; x = sp.Symbol('x'); res = str(sp.diff(x**2, x))",
    )
    assert res.verified is True
    assert res.method == "sympy"


def test_verify_numerical_solution_within_tolerance() -> None:
    res = verify_math_solution(
        claim="Sum of 1/2^n from 1 to 10 is approx 0.999",
        expected=0.9990234375,
        script="res = sum(1/(2**n) for n in range(1, 11))",
    )
    assert res.verified is True
    assert res.error_bound is not None
    assert res.error_bound < 1e-5


def test_equivalent_symbolic_forms_match() -> None:
    res = verify_math_solution(
        claim="(x+1)^2 expands",
        expected="x**2 + 2*x + 1",
        script="import sympy as sp; x = sp.Symbol('x'); res = sp.expand((x + 1)**2)",
    )
    assert res.verified is True


def test_wrong_numeric_claim_is_rejected() -> None:
    res = verify_math_solution(claim="2+2=5", expected=5, script="res = 2 + 2")
    assert res.verified is False
    assert res.error_bound == pytest.approx(1.0)


def test_wrong_symbolic_claim_is_rejected() -> None:
    res = verify_math_solution(
        claim="d/dx x^2 = x",
        expected="x",
        script="import sympy as sp; x = sp.Symbol('x'); res = sp.diff(x**2, x)",
    )
    assert res.verified is False


def test_script_error_is_reported_not_raised() -> None:
    res = verify_math_solution(claim="boom", expected=1, script="res = 1 / 0")
    assert res.verified is False
    assert "ZeroDivisionError" in res.detail


def test_missing_result_variable_is_reported() -> None:
    res = verify_math_solution(claim="no res", expected=1, script="y = 1")
    assert res.verified is False
    assert "res" in res.detail


def test_nan_result_never_verifies() -> None:
    res = verify_math_solution(claim="nan", expected=0.0, script="res = float('nan')")
    assert res.verified is False


def test_runaway_script_is_killed_by_timeout() -> None:
    res = verify_math_solution(
        claim="loop", expected=1, script="while True:\n    pass", timeout_s=1.0
    )
    assert res.verified is False
    assert "timed out" in res.detail


def test_parent_secrets_are_not_visible_to_the_script(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SWARM_TEST_SECRET", "hunter2")
    res = verify_math_solution(
        claim="env isolation",
        expected="none",
        script="import os; res = os.environ.get('SWARM_TEST_SECRET', 'none')",
    )
    assert res.verified is True
