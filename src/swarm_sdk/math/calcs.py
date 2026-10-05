"""Unified SymPy symbolic calculus and PyArrow columnar compute engine for SwarmSDK."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

# ---------------------------------------------------------------------------
# 1. SymPy Symbolic Calculations
# ---------------------------------------------------------------------------


class SympyCalcs:
    """Symbolic mathematical calculations powered by SymPy.

    Provides exact analytical algebra, calculus, matrix manipulation, and
    formal equivalence proofs with lazy module resolution.
    """

    @staticmethod
    def _sp() -> Any:
        import sympy as sp

        return sp

    @classmethod
    def solve(cls, equation: str | Any, symbol: str = "x") -> list[str]:
        """Solves a symbolic algebraic equation for a given variable.

        Example:
            solve("x**2 - 4", "x") -> ["-2", "2"]
        """
        sp = cls._sp()
        sym = sp.Symbol(symbol)
        expr = sp.sympify(equation)
        solutions = sp.solve(expr, sym)
        return [str(s) for s in solutions]

    @classmethod
    def diff(cls, expr: str | Any, symbol: str = "x", order: int = 1) -> str:
        """Computes the symbolic derivative of an expression with respect to a symbol."""
        sp = cls._sp()
        sym = sp.Symbol(symbol)
        e = sp.sympify(expr)
        derivative = sp.diff(e, sym, order)
        return str(derivative)

    @classmethod
    def integrate(
        cls,
        expr: str | Any,
        symbol: str = "x",
        lower: float | None = None,
        upper: float | None = None,
    ) -> str:
        """Computes indefinite or definite symbolic integral of an expression."""
        sp = cls._sp()
        sym = sp.Symbol(symbol)
        e = sp.sympify(expr)
        if lower is not None and upper is not None:
            res = sp.integrate(e, (sym, lower, upper))
        else:
            res = sp.integrate(e, sym)
        return str(res)

    @classmethod
    def simplify(cls, expr: str | Any) -> str:
        """Simplifies an algebraic or trigonometric expression into canonical form."""
        sp = cls._sp()
        e = sp.sympify(expr)
        return str(sp.simplify(e))

    @classmethod
    def matrix_det(cls, matrix: list[list[float | int]]) -> str:
        """Computes the exact symbolic or numerical determinant of a square matrix."""
        sp = cls._sp()
        m = sp.Matrix(matrix)
        return str(m.det())

    @classmethod
    def matrix_inv(cls, matrix: list[list[float | int]]) -> list[list[str]]:
        """Computes the exact symbolic inverse of a square non-singular matrix."""
        sp = cls._sp()
        m = sp.Matrix(matrix)
        inv = m.inv()
        return [[str(inv[r, c]) for c in range(inv.cols)] for r in range(inv.rows)]

    @classmethod
    def verify_identity(cls, lhs: str | Any, rhs: str | Any) -> bool:
        """Proves whether two algebraic expressions are mathematically identical."""
        sp = cls._sp()
        e1 = sp.sympify(lhs)
        e2 = sp.sympify(rhs)
        return bool(sp.simplify(e1 - e2) == 0)


# ---------------------------------------------------------------------------
# 2. PyArrow Columnar & High-Throughput Calculations
# ---------------------------------------------------------------------------


class ArrowCalcs:
    """High-throughput columnar vector and statistical calculations powered by Apache Arrow.

    Operates on zero-copy contiguous memory buffers via pyarrow.compute, with
    high-precision fallback for environments where pyarrow is not installed.
    """

    @staticmethod
    def is_available() -> bool:
        """True if pyarrow is installed and available in the current environment."""
        import importlib.util

        return importlib.util.find_spec("pyarrow") is not None

    @classmethod
    def column_stats(cls, data: Sequence[float | int] | Any) -> dict[str, float]:
        """Calculates moments and median (count, mean, stddev, sum, min, median, max, variance)."""
        if not data:
            return {
                "count": 0.0,
                "mean": 0.0,
                "stddev": 0.0,
                "sum": 0.0,
                "min": 0.0,
                "max": 0.0,
                "variance": 0.0,
                "median": 0.0,
            }

        try:
            import pyarrow as pa  # type: ignore
            import pyarrow.compute as pc  # type: ignore

            arr = pa.array(data, type=pa.float64())
            count = len(arr)
            mean_val = pc.mean(arr).as_py() or 0.0
            std_val = pc.stddev(arr).as_py() or 0.0
            sum_val = pc.sum(arr).as_py() or 0.0
            min_val = pc.min(arr).as_py() or 0.0
            max_val = pc.max(arr).as_py() or 0.0
            var_val = pc.variance(arr).as_py() or 0.0
            med_scalar = pc.quantile(arr, q=0.5)[0].as_py() or 0.0

            return {
                "count": float(count),
                "mean": round(float(mean_val), 6),
                "stddev": round(float(std_val), 6),
                "sum": round(float(sum_val), 6),
                "min": round(float(min_val), 6),
                "median": round(float(med_scalar), 6),
                "max": round(float(max_val), 6),
                "variance": round(float(var_val), 6),
            }
        except (ImportError, Exception):
            # Pure Python fallback
            nums = sorted(float(x) for x in data)
            n = len(nums)
            s = sum(nums)
            m = s / n
            var = sum((x - m) ** 2 for x in nums) / n
            std = math.sqrt(var)
            median = (nums[n // 2] if n % 2 else (nums[n // 2 - 1] + nums[n // 2]) / 2.0)
            return {
                "count": float(n),
                "mean": round(m, 6),
                "stddev": round(std, 6),
                "sum": round(s, 6),
                "min": round(min(nums), 6),
                "median": round(median, 6),
                "max": round(max(nums), 6),
                "variance": round(var, 6),
            }

    @classmethod
    def vector_dot(cls, a: Sequence[float], b: Sequence[float]) -> float:
        """Computes inner product between two dense vectors using Arrow chunked compute or SIMD."""
        if len(a) != len(b):
            raise ValueError(f"Vector dimension mismatch: {len(a)} != {len(b)}")
        if not a:
            return 0.0

        try:
            import pyarrow as pa  # type: ignore
            import pyarrow.compute as pc  # type: ignore

            arr_a = pa.array(a, type=pa.float64())
            arr_b = pa.array(b, type=pa.float64())
            prod = pc.multiply(arr_a, arr_b)
            return float(pc.sum(prod).as_py() or 0.0)
        except (ImportError, Exception):
            return sum(x * y for x, y in zip(a, b))

    @classmethod
    def cosine_similarity(cls, u: Sequence[float], v: Sequence[float]) -> float:
        """Computes cosine similarity in [-1.0, 1.0] between two vectors."""
        if len(u) != len(v):
            raise ValueError(f"Vector dimension mismatch: {len(u)} != {len(v)}")
        dot = cls.vector_dot(u, v)
        norm_u = math.sqrt(cls.vector_dot(u, u))
        norm_v = math.sqrt(cls.vector_dot(v, v))
        if norm_u == 0.0 or norm_v == 0.0:
            return 0.0
        return max(-1.0, min(1.0, dot / (norm_u * norm_v)))

    @classmethod
    def quantiles(
        cls,
        data: Sequence[float],
        q: Sequence[float] = (0.5, 0.95, 0.99),
    ) -> dict[float, float]:
        """Computes exact empirical quantiles for latency and performance profiling."""
        if not data:
            return {float(qi): 0.0 for qi in q}

        try:
            import pyarrow as pa  # type: ignore
            import pyarrow.compute as pc  # type: ignore

            arr = pa.array(data, type=pa.float64())
            res = pc.quantile(arr, q=q)
            return {float(q_val): float(val.as_py()) for q_val, val in zip(q, res)}
        except (ImportError, Exception):
            # Linear-interpolation fallback matching NumPy semantics.
            sorted_nums = sorted(float(x) for x in data)
            n = len(sorted_nums)
            out: dict[float, float] = {}
            for q_val in q:
                pos = q_val * (n - 1)
                low = int(pos)
                high = min(n - 1, low + 1)
                frac = pos - low
                out[float(q_val)] = sorted_nums[low] + frac * (sorted_nums[high] - sorted_nums[low])
            return out

    @classmethod
    def to_arrow_table(cls, data: dict[str, list[Any]]) -> Any:
        """Converts dictionary of columns into an Apache Arrow Table."""
        import pyarrow as pa  # type: ignore

        return pa.Table.from_pydict(data)


# ---------------------------------------------------------------------------
# 3. Unified Math Facade
# ---------------------------------------------------------------------------


class SwarmCalcs:
    """Unified mathematical calculation engine bridging SymPy symbolic and PyArrow columnar math."""

    sympy = SympyCalcs
    arrow = ArrowCalcs


__all__ = ["ArrowCalcs", "SwarmCalcs", "SympyCalcs"]
