"""Tests for SympyCalcs and ArrowCalcs in SwarmSDK math domain."""

from __future__ import annotations

from swarm_sdk.math.calcs import ArrowCalcs, SwarmCalcs, SympyCalcs
from swarm_sdk.math.dispatch import classify_math_task
from swarm_sdk.math.types import MathProblem


class TestSympyCalcs:
    """Test SymPy symbolic calculations: algebra, calculus, matrices, and identity proofs."""

    def test_symbolic_solve_quadratic(self) -> None:
        sols = SympyCalcs.solve("x**2 - 9", "x")
        assert "-3" in sols and "3" in sols

    def test_symbolic_differentiation(self) -> None:
        deriv = SympyCalcs.diff("x**3 + 2*x", "x")
        assert "3*x**2 + 2" in deriv

    def test_symbolic_integration_indefinite_and_definite(self) -> None:
        indef = SympyCalcs.integrate("3*x**2", "x")
        assert "x**3" in indef

        definite = SympyCalcs.integrate("x", "x", 0, 4)
        assert definite == "8"

    def test_symbolic_simplify_trig_identity(self) -> None:
        simplified = SympyCalcs.simplify("sin(x)**2 + cos(x)**2")
        assert simplified == "1"

    def test_symbolic_matrix_determinant(self) -> None:
        det = SympyCalcs.matrix_det([[1, 2], [3, 4]])
        assert det == "-2"

    def test_symbolic_matrix_inverse(self) -> None:
        inv = SympyCalcs.matrix_inv([[1, 0], [0, 2]])
        assert inv == [["1", "0"], ["0", "1/2"]]

    def test_symbolic_verify_identity(self) -> None:
        assert SympyCalcs.verify_identity("(x + 1)**2", "x**2 + 2*x + 1") is True
        assert SympyCalcs.verify_identity("(x + 1)**2", "x**2 + 1") is False


class TestArrowCalcs:
    """Test PyArrow columnar calculations: stats, vector products, and quantiles."""

    def test_column_stats_calculation(self) -> None:
        data = [10.0, 20.0, 30.0, 40.0, 50.0]
        stats = ArrowCalcs.column_stats(data)
        assert stats["count"] == 5.0
        assert stats["mean"] == 30.0
        assert stats["sum"] == 150.0
        assert stats["min"] == 10.0
        assert stats["max"] == 50.0
        assert stats["variance"] > 0.0

    def test_vector_dot_product(self) -> None:
        u = [1.0, 2.0, 3.0]
        v = [4.0, 5.0, 6.0]
        dot = ArrowCalcs.vector_dot(u, v)
        assert dot == 32.0  # 1*4 + 2*5 + 3*6 = 4 + 10 + 18 = 32

    def test_cosine_similarity(self) -> None:
        orthogonal = ArrowCalcs.cosine_similarity([1.0, 0.0], [0.0, 1.0])
        assert orthogonal == 0.0

        identical = ArrowCalcs.cosine_similarity([3.0, 4.0], [3.0, 4.0])
        assert round(identical, 4) == 1.0

    def test_quantiles_calculation(self) -> None:
        data = [float(i) for i in range(1, 101)]
        q_res = ArrowCalcs.quantiles(data, q=[0.5, 0.95])
        assert 49.0 <= q_res[0.5] <= 51.0
        assert 94.0 <= q_res[0.95] <= 96.0

    def test_column_stats_includes_median(self) -> None:
        stats = ArrowCalcs.column_stats([1.0, 2.0, 3.0, 4.0, 5.0])
        assert stats["median"] == 3.0
        stats_even = ArrowCalcs.column_stats([1.0, 2.0, 3.0, 4.0])
        assert stats_even["median"] == 2.5

    def test_quantiles_use_linear_interpolation(self) -> None:
        # Even-count data: median should be interpolated, not floored.
        data = [1.0, 2.0, 3.0, 4.0]
        q_res = ArrowCalcs.quantiles(data, q=[0.5])
        assert q_res[0.5] == pytest.approx(2.5)


class TestSwarmCalcsFacadeAndDispatch:
    """Test unified SwarmCalcs facade and dispatch routing."""

    def test_unified_facade_access(self) -> None:
        assert SwarmCalcs.sympy.diff("x**2", "x") == "2*x"
        stats = SwarmCalcs.arrow.column_stats([1.0, 2.0, 3.0])
        assert stats["mean"] == 2.0

    def test_dispatch_routing_to_sympy(self) -> None:
        prob = MathProblem(
            problem_statement="symbolic solve derivative of sin(x)",
            task_type="calculus",
            mode="solve",
        )
        decision = classify_math_task(prob)
        assert decision.backend == "sympy"
        assert decision.selected_route["provider"] == "local_cpu"

    def test_dispatch_routing_to_pyarrow(self) -> None:
        prob = MathProblem(
            problem_statement="compute arrow column stats for latency table",
            task_type="stats",
            mode="solve",
        )
        decision = classify_math_task(prob)
        assert decision.backend == "pyarrow"
        assert decision.selected_route["provider"] == "local_cpu"
