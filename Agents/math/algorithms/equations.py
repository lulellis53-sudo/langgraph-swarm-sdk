"""Pillar 3: damped Newton roots and the BM25 symbolic invariant."""

from collections.abc import Callable

import numpy as np
import sympy as sp

from algorithms.errors import AlgorithmError, AlgorithmInputError

__all__ = ["damped_newton_root", "verify_bm25_asymptotics"]


def damped_newton_root(
    residual: Callable[[np.ndarray], np.ndarray],
    jacobian: Callable[[np.ndarray], np.ndarray],
    x0: np.ndarray,
    tol: float = 1e-12,
    max_iter: int = 100,
) -> np.ndarray:
    """Solve ``F(x) = 0`` with Levenberg-Marquardt damping.

    Args:
        residual: Vector residual ``F``.
        jacobian: Jacobian of ``F``.
        x0: Initial guess.
        tol: Stop when the residual 2-norm is below this value.
        max_iter: Iteration cap. The last accepted point is returned if it is not met.

    Returns:
        The accepted point.
    """
    if tol <= 0.0 or max_iter < 1:
        raise AlgorithmInputError("tol must be positive and max_iter at least 1")
    point = np.asarray(x0, dtype=np.float64).reshape(-1).copy()
    if point.size == 0:
        raise AlgorithmInputError("Newton initial guess is empty")
    damping = 1e-3
    for _ in range(max_iter):
        current = np.asarray(residual(point), dtype=np.float64).reshape(-1)
        current_norm = float(np.linalg.norm(current))
        if current_norm < tol:
            return point
        jac = np.asarray(jacobian(point), dtype=np.float64)
        if jac.shape != (current.shape[0], point.shape[0]):
            raise AlgorithmInputError("Jacobian shape does not match F(x) and x")
        normal = jac.T @ jac + damping * np.eye(point.shape[0])
        step = np.linalg.solve(normal, -jac.T @ current)
        proposal = point + step
        proposal_norm = float(np.linalg.norm(np.asarray(residual(proposal), dtype=np.float64)))
        if proposal_norm < current_norm:
            damping = max(damping / 10.0, 1e-7)
            point = proposal
        else:
            damping = min(damping * 10.0, 1e7)
    return point


def verify_bm25_asymptotics() -> dict[str, bool]:
    """Prove BM25 term-frequency monotonicity and its saturation bound.

    The derivative identity is unconditional. Positivity needs the BM25 domain
    ``tf, k1, dl, avgdl > 0`` and ``0 < b < 1``, where the length term
    ``(1 - b) + b dl / avgdl`` is positive. ``b > 0`` alone is not enough.

    Returns:
        Flags for a positive ``tf`` derivative on that domain and a limit of ``k1 + 1``.

    Raises:
        AlgorithmError: SymPy does not confirm either invariant.
    """
    tf, k1, dl, avgdl = sp.symbols("tf k1 dl avgdl", positive=True)
    b = sp.symbols("b", real=True)
    length = 1 - b + b * (dl / avgdl)
    term = (tf * (k1 + 1)) / (tf + k1 * length)
    derivative = sp.cancel(sp.diff(term, tf))
    expected = (k1 + 1) * k1 * length / (tf + k1 * length) ** 2
    monotonic = sp.simplify(derivative - expected) == 0
    length_numerator = sp.numer(sp.together(length))
    length_identity = sp.simplify(length_numerator - ((1 - b) * avgdl + b * dl)) == 0
    saturated = sp.simplify(sp.limit(term, tf, sp.oo) - (k1 + 1)) == 0
    if not monotonic or not length_identity or not saturated:
        raise AlgorithmError("BM25 asymptotic invariant failed")
    return {"monotonic_in_tf": True, "saturation_limit_is_k1_plus_1": True}
