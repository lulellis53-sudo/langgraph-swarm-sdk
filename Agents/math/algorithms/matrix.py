"""Pillar 5: Householder QR, Cholesky, CSR SpMV, and the 2-norm condition number."""

import numpy as np

from algorithms.errors import AlgorithmInputError, NotPositiveDefiniteError

__all__ = [
    "cholesky_factorization",
    "condition_number_2",
    "householder_qr",
    "spmv_csr",
    "truncated_svd",
]


def condition_number_2(matrix: np.ndarray) -> float:
    """Return the 2-norm condition number, or infinity when the matrix is singular."""
    data = np.asarray(matrix, dtype=np.float64)
    if data.ndim != 2 or data.size == 0:
        raise AlgorithmInputError("condition number requires a non-empty 2-D matrix")
    singular = np.linalg.svd(data, compute_uv=False)
    if singular.size == 0 or singular[-1] == 0.0:
        return float("inf")
    return float(singular[0] / singular[-1])


def householder_qr(matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Factor a matrix with Householder reflectors.

    Returns:
        ``Q`` and ``R`` such that ``A = Q @ R`` and ``Q`` has orthonormal columns
        when ``A`` has full column rank. ``Q`` is square.
    """
    data = np.asarray(matrix, dtype=np.float64)
    if data.ndim != 2 or data.size == 0:
        raise AlgorithmInputError("QR requires a non-empty 2-D matrix")
    rows, cols = data.shape
    orthogonal = np.eye(rows, dtype=np.float64)
    upper = data.copy()
    for column in range(min(rows - 1, cols)):
        reflector = upper[column:rows, column].copy()
        norm = float(np.linalg.norm(reflector))
        if norm == 0.0:
            continue
        pivot = float(reflector[0])
        alpha = -norm if pivot == 0.0 else -float(np.sign(pivot)) * norm
        reflector[0] -= alpha
        direction = reflector / float(np.linalg.norm(reflector))
        trailing = upper[column:rows, column:]
        upper[column:rows, column:] = trailing - 2.0 * np.outer(direction, direction @ trailing)
        block = orthogonal[:, column:rows]
        orthogonal[:, column:rows] = block - 2.0 * np.outer(block @ direction, direction)
    return orthogonal, upper


def cholesky_factorization(matrix: np.ndarray) -> np.ndarray:
    """Return the lower Cholesky factor of a symmetric positive definite matrix.

    Raises:
        NotPositiveDefiniteError: A diagonal pivot is not positive.
    """
    data = np.asarray(matrix, dtype=np.float64)
    if data.ndim != 2 or data.shape[0] != data.shape[1] or data.shape[0] == 0:
        raise AlgorithmInputError("Cholesky requires a non-empty square matrix")
    scale = max(1.0, float(np.max(np.abs(data))))
    if not np.allclose(data, data.T, rtol=0.0, atol=1e-8 * scale):
        raise AlgorithmInputError("Cholesky requires a symmetric matrix")
    size = data.shape[0]
    factor = np.zeros((size, size), dtype=np.float64)
    for row in range(size):
        for col in range(row + 1):
            dot = float(sum(factor[row, k] * factor[col, k] for k in range(col)))
            if row == col:
                pivot = float(data[row, row] - dot)
                if pivot <= 0.0:
                    raise NotPositiveDefiniteError("matrix is not symmetric positive definite")
                factor[row, col] = float(np.sqrt(pivot))
            else:
                factor[row, col] = (float(data[row, col]) - dot) / factor[col, col]
    return factor


def spmv_csr(
    data: np.ndarray,
    indices: np.ndarray,
    indptr: np.ndarray,
    vector: np.ndarray,
) -> np.ndarray:
    """Multiply a CSR matrix by a dense vector."""
    values = np.asarray(data)
    columns = np.asarray(indices, dtype=np.int64).reshape(-1)
    pointers = np.asarray(indptr, dtype=np.int64).reshape(-1)
    dense = np.asarray(vector).reshape(-1)
    if pointers.size < 1 or pointers[0] != 0 or pointers[-1] != values.size:
        raise AlgorithmInputError("CSR indptr does not span the value array")
    if np.any(np.diff(pointers) < 0):
        raise AlgorithmInputError("CSR indptr is not non-decreasing")
    if columns.shape != values.shape:
        raise AlgorithmInputError("CSR indices and values must have the same length")
    if columns.size and (int(columns.min()) < 0 or int(columns.max()) >= dense.shape[0]):
        raise AlgorithmInputError("CSR column index is outside the vector")
    rows = pointers.size - 1
    product = np.zeros(rows, dtype=np.result_type(values, dense, np.float64))
    for row in range(rows):
        start = int(pointers[row])
        stop = int(pointers[row + 1])
        product[row] = np.dot(values[start:stop], dense[columns[start:stop]])
    return product


def truncated_svd(matrix: np.ndarray, rank: int) -> dict[str, object]:
    """Return the optimal rank-``rank`` approximation with its Eckart-Young errors.

    By the Eckart-Young-Mirsky theorem the truncated SVD minimizes both the
    spectral and the Frobenius error among all matrices of rank at most ``rank``:
    ``min ||A - B||_2 = sigma_{rank+1}`` and
    ``min ||A - B||_F = sqrt(sum_{i > rank} sigma_i^2)``.

    Args:
        matrix: Input of shape ``(m, n)``.
        rank: Target rank. Between 1 and ``min(m, n)``.

    Returns:
        Dict with the approximation ``"approx"``, the spectral error
        ``"spectral_error"``, and the Frobenius error ``"frobenius_error"``.

    Raises:
        AlgorithmInputError: The rank is outside ``1..min(m, n)`` or the shape is invalid.
    """
    values = np.asarray(matrix, dtype=np.float64)
    if values.ndim != 2 or min(values.shape) < 1:
        raise AlgorithmInputError("truncated SVD needs a non-empty 2-D matrix")
    if rank < 1 or rank > min(values.shape):
        raise AlgorithmInputError("rank must be between 1 and min(m, n)")
    left, singular, right = np.linalg.svd(values, full_matrices=False)
    approximation = left[:, :rank] @ np.diag(singular[:rank]) @ right[:rank, :]
    tail = singular[rank:]
    spectral = float(tail[0]) if tail.size else 0.0
    frobenius = float(np.sqrt(np.sum(tail * tail))) if tail.size else 0.0
    return {
        "approx": approximation,
        "spectral_error": spectral,
        "frobenius_error": frobenius,
    }
