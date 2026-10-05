"""Pillar 7: cancellation shields, block inversion, quadrature, and compensated sums."""

import numpy as np

from algorithms.errors import AlgorithmInputError

__all__ = [
    "cos_diff",
    "cramer_rao_bound",
    "expm1_stable",
    "golub_welsch_legendre",
    "kahan_sum",
    "log1p_stable",
    "log_sum_exp",
    "one_minus_cos",
    "reciprocal_gap",
    "schur_complement_inverse",
    "sqrt_diff_stable",
    "stable_quadratic_roots",
    "woodbury_inverse",
]


def sqrt_diff_stable(value: float) -> float:
    """Evaluate ``sqrt(x + 1) - sqrt(x)`` without cancellation for large ``x``."""
    if value < 0.0:
        raise AlgorithmInputError("sqrt difference is defined for x >= 0")
    return 1.0 / (float(np.sqrt(value + 1.0)) + float(np.sqrt(value)))


def one_minus_cos(value: float) -> float:
    """Evaluate ``1 - cos(x)`` as ``2 sin^2(x / 2)``."""
    return float(2.0 * np.sin(value / 2.0) ** 2)


def log1p_stable(value: float) -> float:
    """Evaluate ``log(1 + x)`` with ``numpy.log1p``."""
    if value <= -1.0:
        raise AlgorithmInputError("log1p requires x > -1")
    return float(np.log1p(value))


def expm1_stable(value: float) -> float:
    """Evaluate ``exp(x) - 1`` with ``numpy.expm1``."""
    return float(np.expm1(value))


def reciprocal_gap(value: float) -> float:
    """Evaluate ``1/x - 1/(x + 1)`` as ``1 / (x (x + 1))``."""
    if value == 0.0 or value == -1.0:
        raise AlgorithmInputError("reciprocal gap is undefined at 0 and -1")
    return 1.0 / (value * (value + 1.0))


def cos_diff(left: float, right: float) -> float:
    """Evaluate ``cos(x) - cos(y)`` with a product of sines."""
    return float(-2.0 * np.sin((left + right) / 2.0) * np.sin((left - right) / 2.0))


def log_sum_exp(values: np.ndarray) -> float:
    """Evaluate ``log(sum(exp(z)))`` after subtracting the maximum."""
    data = np.asarray(values, dtype=np.float64).reshape(-1)
    if data.size == 0:
        raise AlgorithmInputError("log-sum-exp input is empty")
    if not np.all(np.isfinite(data)):
        raise AlgorithmInputError("log-sum-exp input must be finite")
    center = float(np.max(data))
    return center + float(np.log(np.sum(np.exp(data - center))))


def kahan_sum(values: np.ndarray) -> float:
    """Sum a 1-D array with Kahan compensation."""
    data = np.asarray(values, dtype=np.float64).reshape(-1)
    total = 0.0
    compensation = 0.0
    for value in data:
        adjusted = float(value) - compensation
        updated = total + adjusted
        compensation = (updated - total) - adjusted
        total = updated
    return total


def stable_quadratic_roots(a: float, b: float, c: float) -> tuple[float, float]:
    """Return real roots of ``a x^2 + b x + c`` without cancelling the smaller root.

    The larger-magnitude root is computed from the discriminant. The other root
    comes from Vieta's product ``c / a``.

    Raises:
        AlgorithmInputError: The equation is not quadratic or the roots are not real.
    """
    if a == 0.0:
        raise AlgorithmInputError("leading coefficient is zero")
    discriminant = b * b - 4.0 * a * c
    if discriminant < 0.0:
        raise AlgorithmInputError("discriminant is negative")
    sqrt_disc = float(np.sqrt(discriminant))
    if b == 0.0:
        half = sqrt_disc / (2.0 * a)
        return half, -half
    if b > 0.0:
        stable = -b - sqrt_disc
    else:
        stable = -b + sqrt_disc
    primary = stable / (2.0 * a)
    if primary == 0.0:
        return 0.0, 0.0
    return primary, c / (a * primary)


def schur_complement_inverse(
    top_left: np.ndarray,
    top_right: np.ndarray,
    bottom_left: np.ndarray,
    bottom_right: np.ndarray,
) -> np.ndarray:
    """Invert a block matrix from the Schur complement of the lower-right block."""
    a = np.asarray(top_left, dtype=np.float64)
    b = np.asarray(top_right, dtype=np.float64)
    c = np.asarray(bottom_left, dtype=np.float64)
    d = np.asarray(bottom_right, dtype=np.float64)
    if a.ndim != 2 or d.ndim != 2 or a.shape[0] != a.shape[1] or d.shape[0] != d.shape[1]:
        raise AlgorithmInputError("Schur blocks A and D must be square")
    if b.shape != (a.shape[0], d.shape[0]) or c.shape != (d.shape[0], a.shape[0]):
        raise AlgorithmInputError("Schur off-diagonal blocks have the wrong shape")
    d_inv = np.linalg.inv(d)
    schur = a - b @ d_inv @ c
    schur_inv = np.linalg.inv(schur)
    upper_left = schur_inv
    upper_right = -schur_inv @ b @ d_inv
    lower_left = -d_inv @ c @ schur_inv
    lower_right = d_inv + d_inv @ c @ schur_inv @ b @ d_inv
    return np.block([[upper_left, upper_right], [lower_left, lower_right]])


def woodbury_inverse(
    base_inverse: np.ndarray,
    left: np.ndarray,
    core: np.ndarray,
    right: np.ndarray,
) -> np.ndarray:
    """Invert ``A + U C V`` from ``A^{-1}`` with the Woodbury identity."""
    a_inv = np.asarray(base_inverse, dtype=np.float64)
    u = np.asarray(left, dtype=np.float64)
    c = np.asarray(core, dtype=np.float64)
    v = np.asarray(right, dtype=np.float64)
    if a_inv.ndim != 2 or a_inv.shape[0] != a_inv.shape[1]:
        raise AlgorithmInputError("Woodbury base inverse must be square")
    if u.ndim != 2 or v.ndim != 2 or c.ndim != 2:
        raise AlgorithmInputError("Woodbury factors U, C, and V must be 2-D")
    if u.shape[0] != a_inv.shape[0] or v.shape[1] != a_inv.shape[0]:
        raise AlgorithmInputError("Woodbury factors do not match the base dimension")
    if c.shape != (u.shape[1], v.shape[0]) or u.shape[1] != v.shape[0]:
        raise AlgorithmInputError("Woodbury core does not match U and V")
    middle = np.linalg.inv(c) + v @ a_inv @ u
    return a_inv - a_inv @ u @ np.linalg.inv(middle) @ v @ a_inv


def golub_welsch_legendre(n_points: int) -> tuple[np.ndarray, np.ndarray]:
    """Return Gauss-Legendre nodes and weights from the Jacobi companion matrix.

    Args:
        n_points: Number of nodes. At least 1.

    Returns:
        Nodes on ``[-1, 1]`` and weights that sum to 2.
    """
    if n_points < 1:
        raise AlgorithmInputError("Gauss-Legendre order must be positive")
    index = np.arange(1, n_points, dtype=np.float64)
    beta = index / np.sqrt(4.0 * index * index - 1.0)
    jacobi = np.diag(beta, k=1) + np.diag(beta, k=-1)
    eigenvalues, eigenvectors = np.linalg.eigh(jacobi)
    return eigenvalues, 2.0 * (eigenvectors[0, :] ** 2)


def cramer_rao_bound(fisher_information: float | np.ndarray) -> float | np.ndarray:
    """Invert the Fisher information into the Cramer-Rao lower bound.

    For a scalar parameter the bound is ``Var(theta_hat) >= 1 / I(theta)``; for a
    parameter vector with information matrix ``I`` the covariance bound is ``I^-1``
    entrywise, and the bound applies to unbiased estimators only.

    Args:
        fisher_information: Positive scalar, or a symmetric positive definite
            information matrix of shape ``(k, k)``.

    Returns:
        ``1 / I`` as a float, or the inverse matrix ``I^-1``.

    Raises:
        AlgorithmInputError: The information is not positive, not finite, or the
            matrix is not square symmetric positive definite.
    """
    information = np.asarray(fisher_information, dtype=np.float64)
    if information.ndim == 0:
        value = float(information)
        if not np.isfinite(value) or value <= 0.0:
            raise AlgorithmInputError("Fisher information must be positive and finite")
        return 1.0 / value
    if information.ndim != 2 or information.shape[0] != information.shape[1]:
        raise AlgorithmInputError("Fisher information matrix must be square")
    if not np.all(np.isfinite(information)):
        raise AlgorithmInputError("Fisher information must be finite")
    if not np.allclose(information, information.T, rtol=1e-12, atol=0.0):
        raise AlgorithmInputError("Fisher information matrix must be symmetric")
    try:
        inverse = np.linalg.inv(information)
    except np.linalg.LinAlgError as err:
        raise AlgorithmInputError("Fisher information matrix is singular") from err
    if np.any(np.linalg.eigvalsh((information + information.T) / 2.0) <= 0.0):
        raise AlgorithmInputError("Fisher information matrix must be positive definite")
    return inverse
