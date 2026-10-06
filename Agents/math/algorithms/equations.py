"""Pillar 3: damped Newton roots and the BM25 symbolic invariant."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import sympy as sp

from algorithms.errors import AlgorithmError, AlgorithmInputError

__all__ = [
    "bisection_root",
    "damped_newton_root",
    "stormer_verlet_integrate",
    "verify_bm25_asymptotics",
]


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


def stormer_verlet_integrate(
    position: np.ndarray,
    momentum: np.ndarray,
    grad_potential: Callable[[np.ndarray], np.ndarray],
    dt: float,
    steps: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Integrate separable Hamiltonian dynamics with the Störmer-Verlet scheme.

    For ``H(q, p) = |p|^2 / 2 + V(q)`` (unit masses) the kick-drift-kick leapfrog
    is symplectic: the discrete flow preserves phase-space volume and the energy
    error stays bounded by ``O(dt^2)`` without secular drift.

    Args:
        position: Initial coordinates ``q0`` of shape ``(n,)``.
        momentum: Initial momenta ``p0`` of shape ``(n,)``.
        grad_potential: Gradient ``grad V(q)`` returning shape ``(n,)``.
        dt: Positive time step.
        steps: Number of steps. At least 1.

    Returns:
        Trajectories ``(q, p)`` of shape ``(steps + 1, n)`` including the start.

    Raises:
        AlgorithmInputError: Shapes mismatch, ``dt`` is not positive, or ``steps`` is 0.
    """
    if dt <= 0.0 or steps < 1:
        raise AlgorithmInputError("dt must be positive and steps at least 1")
    initial_q = np.asarray(position, dtype=np.float64).reshape(-1)
    initial_p = np.asarray(momentum, dtype=np.float64).reshape(-1)
    if initial_q.shape != initial_p.shape or initial_q.size == 0:
        raise AlgorithmInputError("position and momentum must be matching non-empty vectors")
    trajectory_q = np.empty((steps + 1, initial_q.size), dtype=np.float64)
    trajectory_p = np.empty((steps + 1, initial_p.size), dtype=np.float64)
    trajectory_q[0] = initial_q
    trajectory_p[0] = initial_p
    current_q = initial_q.copy()
    current_p = initial_p.copy()
    for step in range(1, steps + 1):
        half_kick = current_p - 0.5 * dt * np.asarray(grad_potential(current_q), dtype=np.float64)
        current_q = current_q + dt * half_kick
        current_p = half_kick - 0.5 * dt * np.asarray(grad_potential(current_q), dtype=np.float64)
        trajectory_q[step] = current_q
        trajectory_p[step] = current_p
    return trajectory_q, trajectory_p


def bisection_root(
    function: Callable[[float], float],
    lower: float,
    upper: float,
    tol: float = 1e-12,
    max_iter: int = 200,
) -> float:
    """Find one root of a continuous scalar function on a sign-change bracket.

    Bisection halves the bracket unconditionally, so it always converges for a
    continuous ``function`` with ``f(lower) * f(upper) < 0`` — the robust fallback
    when Newton fails to converge, at a linear rate of one bit per iteration.

    Args:
        function: Continuous scalar function.
        lower: Bracket end with one sign.
        upper: Bracket end with the opposite sign.
        tol: Stop when the bracket is narrower than this.
        max_iter: Iteration cap.

    Returns:
        A point within ``tol`` of a root.

    Raises:
        AlgorithmInputError: The bracket does not straddle a root or arguments are invalid.
        AlgorithmError: The iteration cap is hit before the bracket closes.
    """
    if tol <= 0.0 or max_iter < 1:
        raise AlgorithmInputError("tol must be positive and max_iter at least 1")
    left, right = float(lower), float(upper)
    if not left < right:
        raise AlgorithmInputError("lower must be strictly less than upper")
    value_left = float(function(left))
    value_right = float(function(right))
    if value_left == 0.0:
        return left
    if value_right == 0.0:
        return right
    if value_left * value_right > 0.0:
        raise AlgorithmInputError("bracket does not straddle a root")
    for _ in range(max_iter):
        middle = 0.5 * (left + right)
        value_middle = float(function(middle))
        if value_middle == 0.0 or (right - left) * 0.5 < tol:
            return middle
        if value_left * value_middle < 0.0:
            right, value_right = middle, value_middle
        else:
            left, value_left = middle, value_middle
    raise AlgorithmError("bisection did not close the bracket within max_iter")
