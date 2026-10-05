"""Arrow-backed numeric reductions and distance metrics."""

import numpy as np

from algorithms.columnar import _pyarrow
from algorithms.errors import AlgorithmDependencyError, AlgorithmInputError

__all__ = [
    "arrow_sum",
    "arrow_mean",
    "arrow_min",
    "arrow_max",
    "arrow_abs",
    "arrow_floor",
    "arrow_ceil",
    "arrow_sign",
    "arrow_median",
    "arrow_geometric_mean",
    "arrow_mean_absolute_deviation",
    "arrow_weighted_mean",
    "arrow_chebyshev_distance",
    "arrow_manhattan_distance",
    "arrow_euclidean_distance",
]


def _kernels() -> tuple[object, object]:
    """Return pyarrow and pyarrow.compute, raising if pyarrow is missing."""
    pa = _pyarrow()
    try:
        import pyarrow.compute as pc
    except ImportError as err:
        raise AlgorithmDependencyError("pyarrow is not installed") from err
    return pa, pc


def _as_float64_array(values: object) -> object:
    """Validate and cast input values to a non-empty finite float64 Arrow array."""
    pa, pc = _kernels()
    arr = values if isinstance(values, pa.Array) else pa.array(values)
    if pa.types.is_boolean(arr.type):
        raise AlgorithmInputError("bool values are not allowed")
    if len(arr) == 0:
        raise AlgorithmInputError("input array must not be empty")
    if arr.null_count > 0:
        raise AlgorithmInputError("input array must not contain nulls")
    arr = pc.cast(arr, pa.float64())
    if not pc.all(pc.is_finite(arr)).as_py():
        raise AlgorithmInputError("input array must contain only finite values")
    return arr


def arrow_sum(values: object) -> float:
    """Return the sum of the values as a float."""
    _, pc = _kernels()
    arr = _as_float64_array(values)
    return float(pc.sum(arr).as_py())


def arrow_mean(values: object) -> float:
    """Return the arithmetic mean of the values as a float."""
    _, pc = _kernels()
    arr = _as_float64_array(values)
    return float(pc.mean(arr).as_py())


def arrow_min(values: object) -> float:
    """Return the minimum value as a float."""
    _, pc = _kernels()
    arr = _as_float64_array(values)
    return float(pc.min(arr).as_py())


def arrow_max(values: object) -> float:
    """Return the maximum value as a float."""
    _, pc = _kernels()
    arr = _as_float64_array(values)
    return float(pc.max(arr).as_py())


def arrow_abs(values: object) -> np.ndarray:
    """Return the element-wise absolute values as a float64 NumPy array."""
    pa, pc = _kernels()
    arr = _as_float64_array(values)
    return pc.cast(pc.abs(arr), pa.float64()).to_numpy()


def arrow_floor(values: object) -> np.ndarray:
    """Return the element-wise floor as a float64 NumPy array."""
    pa, pc = _kernels()
    arr = _as_float64_array(values)
    return pc.cast(pc.floor(arr), pa.float64()).to_numpy()


def arrow_ceil(values: object) -> np.ndarray:
    """Return the element-wise ceiling as a float64 NumPy array."""
    pa, pc = _kernels()
    arr = _as_float64_array(values)
    return pc.cast(pc.ceil(arr), pa.float64()).to_numpy()


def arrow_sign(values: object) -> np.ndarray:
    """Return the element-wise sign as a float64 NumPy array."""
    pa, pc = _kernels()
    arr = _as_float64_array(values)
    return pc.cast(pc.sign(arr), pa.float64()).to_numpy()


def arrow_median(values: object) -> float:
    """Return the median of the values as a float."""
    _, pc = _kernels()
    arr = _as_float64_array(values)
    return float(pc.quantile(arr, q=0.5).to_pylist()[0])


def arrow_geometric_mean(values: object) -> float:
    """Return the geometric mean of positive values as a float."""
    _, pc = _kernels()
    arr = _as_float64_array(values)
    if pc.min(arr).as_py() <= 0:
        raise AlgorithmInputError("values must be positive")
    return float(pc.exp(pc.mean(pc.ln(arr))).as_py())


def arrow_mean_absolute_deviation(values: object) -> float:
    """Return the mean absolute deviation about the mean as a float."""
    _, pc = _kernels()
    arr = _as_float64_array(values)
    mean = pc.mean(arr)
    return float(pc.mean(pc.abs(pc.subtract(arr, mean))).as_py())


def arrow_weighted_mean(values: object, weights: object) -> float:
    """Return the weighted mean of values using the supplied weights."""
    _, pc = _kernels()
    v_arr = _as_float64_array(values)
    w_arr = _as_float64_array(weights)
    if len(v_arr) != len(w_arr):
        raise AlgorithmInputError("values and weights must have the same length")
    if pc.min(w_arr).as_py() < 0:
        raise AlgorithmInputError("weights must be non-negative")
    weight_sum = pc.sum(w_arr).as_py()
    if weight_sum == 0:
        raise AlgorithmInputError("weights must not all be zero")
    weighted = pc.multiply(v_arr, w_arr)
    return float(pc.sum(weighted).as_py() / weight_sum)


def arrow_chebyshev_distance(left: object, right: object) -> float:
    """Return the Chebyshev distance between two equal-length arrays."""
    _, pc = _kernels()
    l_arr = _as_float64_array(left)
    r_arr = _as_float64_array(right)
    if len(l_arr) != len(r_arr):
        raise AlgorithmInputError("inputs must have the same length")
    return float(pc.max(pc.abs(pc.subtract(l_arr, r_arr))).as_py())


def arrow_manhattan_distance(left: object, right: object) -> float:
    """Return the Manhattan distance between two equal-length arrays."""
    _, pc = _kernels()
    l_arr = _as_float64_array(left)
    r_arr = _as_float64_array(right)
    if len(l_arr) != len(r_arr):
        raise AlgorithmInputError("inputs must have the same length")
    return float(pc.sum(pc.abs(pc.subtract(l_arr, r_arr))).as_py())


def arrow_euclidean_distance(left: object, right: object) -> float:
    """Return the Euclidean distance between two equal-length arrays."""
    _, pc = _kernels()
    l_arr = _as_float64_array(left)
    r_arr = _as_float64_array(right)
    if len(l_arr) != len(r_arr):
        raise AlgorithmInputError("inputs must have the same length")
    diff = pc.subtract(l_arr, r_arr)
    return float(pc.sqrt(pc.sum(pc.multiply(diff, diff))).as_py())
