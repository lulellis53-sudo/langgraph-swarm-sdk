"""Residual, backward-error, and condition check for a linear solution."""

import numpy as np

from algorithms.errors import AlgorithmInputError

__all__ = ["verify_numerical_solution"]


def verify_numerical_solution(
    matrix: np.ndarray,
    rhs: np.ndarray,
    solution: np.ndarray,
    tol: float = 1e-12,
) -> dict[str, float | bool]:
    """Check a computed solution of ``A x = b`` against residual and condition bounds.

    Args:
        matrix: Coefficient matrix.
        rhs: Right-hand side.
        solution: Candidate ``x``.
        tol: Pass when the mixed backward error is at most this value.

    Returns:
        Residual norm, backward error, 2-norm condition number, forward-error
        bound, and whether the backward error passed ``tol``.
    """
    if tol <= 0.0:
        raise AlgorithmInputError("verification tolerance must be positive")
    coefficients = np.asarray(matrix, dtype=np.float64)
    target = np.asarray(rhs, dtype=np.float64).reshape(-1)
    estimate = np.asarray(solution, dtype=np.float64).reshape(-1)
    if coefficients.ndim != 2 or coefficients.shape[1] != estimate.shape[0]:
        raise AlgorithmInputError("verification shapes do not match A x")
    if coefficients.shape[0] != target.shape[0]:
        raise AlgorithmInputError("verification shapes do not match A x and b")
    residual = coefficients @ estimate - target
    residual_norm = float(np.linalg.norm(residual))
    matrix_norm = float(np.linalg.norm(coefficients, 2))
    solution_norm = float(np.linalg.norm(estimate))
    rhs_norm = float(np.linalg.norm(target))
    denominator = matrix_norm * solution_norm + rhs_norm
    backward = residual_norm / denominator if denominator > 0.0 else residual_norm
    singular = np.linalg.svd(coefficients, compute_uv=False)
    condition = (
        float("inf")
        if singular.size == 0 or singular[-1] == 0.0
        else float(singular[0] / singular[-1])
    )
    return {
        "residual_norm": residual_norm,
        "backward_error": backward,
        "condition_number": condition,
        "forward_error_bound": condition * backward,
        "passed": backward <= tol,
    }
