"""Pillar 2: tiled matmul, Strassen, radix-2 FFT, and the roofline bound."""

import numpy as np

from algorithms.errors import AlgorithmInputError

__all__ = [
    "attainable_performance",
    "cooley_tukey_fft",
    "strassen_matmul",
    "tiled_matmul",
]


def attainable_performance(
    peak_flops: float,
    bandwidth_bytes_per_second: float,
    flops: float,
    bytes_moved: float,
) -> tuple[float, float, str]:
    """Return operational intensity, attainable FLOP/s, and the active roofline bound.

    Returns:
        Intensity in FLOPs per byte, attainable rate, and ``compute`` or ``memory``.
    """
    if peak_flops <= 0.0 or bandwidth_bytes_per_second <= 0.0:
        raise AlgorithmInputError("peak rate and bandwidth must be positive")
    if flops < 0.0 or bytes_moved <= 0.0:
        raise AlgorithmInputError("bytes moved must be positive and FLOPs non-negative")
    intensity = flops / bytes_moved
    knee = peak_flops / bandwidth_bytes_per_second
    attainable = min(peak_flops, intensity * bandwidth_bytes_per_second)
    bound = "compute" if intensity >= knee else "memory"
    return intensity, attainable, bound


def tiled_matmul(left: np.ndarray, right: np.ndarray, block_size: int = 64) -> np.ndarray:
    """Multiply matrices by cache-sized tiles.

    Args:
        left: Array of shape ``(m, k)``.
        right: Array of shape ``(k, n)``.
        block_size: Tile length. Positive.

    Returns:
        Product of shape ``(m, n)`` in float64.
    """
    a = np.asarray(left, dtype=np.float64)
    b = np.asarray(right, dtype=np.float64)
    if a.ndim != 2 or b.ndim != 2 or a.shape[1] != b.shape[0]:
        raise AlgorithmInputError("tiled matmul requires shapes (m, k) and (k, n)")
    if block_size < 1:
        raise AlgorithmInputError("block_size must be positive")
    rows, shared = a.shape
    cols = b.shape[1]
    product = np.zeros((rows, cols), dtype=np.float64)
    for i0 in range(0, rows, block_size):
        i1 = min(i0 + block_size, rows)
        for j0 in range(0, cols, block_size):
            j1 = min(j0 + block_size, cols)
            for k0 in range(0, shared, block_size):
                k1 = min(k0 + block_size, shared)
                product[i0:i1, j0:j1] += a[i0:i1, k0:k1] @ b[k0:k1, j0:j1]
    return product


def cooley_tukey_fft(values: np.ndarray) -> np.ndarray:
    """Compute a radix-2 Cooley-Tukey DFT.

    Args:
        values: One-dimensional signal whose length is a power of two.

    Returns:
        Complex spectrum using the same sign convention as ``numpy.fft.fft``.
    """
    signal = np.asarray(values)
    if signal.ndim != 1:
        raise AlgorithmInputError("FFT input must be one-dimensional")
    length = int(signal.shape[0])
    if length == 0 or length & (length - 1):
        raise AlgorithmInputError("FFT length must be a positive power of two")
    return _fft(signal.astype(np.complex128, copy=False))


def _fft(signal: np.ndarray) -> np.ndarray:
    length = int(signal.shape[0])
    if length <= 1:
        return signal
    even = _fft(signal[0::2])
    odd = _fft(signal[1::2])
    half = length // 2
    factor = np.exp(-2j * np.pi * np.arange(half) / length)
    return np.concatenate([even + factor * odd, even - factor * odd])


def strassen_matmul(left: np.ndarray, right: np.ndarray, *, leaf: int = 32) -> np.ndarray:
    """Multiply matrices with Strassen's algorithm on a power-of-two pad.

    Args:
        left: Array of shape ``(m, k)``.
        right: Array of shape ``(k, n)``.
        leaf: Size at which the recursion switches to ordinary matmul.

    Returns:
        Product of shape ``(m, n)``. Padding is removed.
    """
    a = np.asarray(left, dtype=np.float64)
    b = np.asarray(right, dtype=np.float64)
    if a.ndim != 2 or b.ndim != 2 or a.shape[1] != b.shape[0]:
        raise AlgorithmInputError("Strassen requires shapes (m, k) and (k, n)")
    if leaf < 1:
        raise AlgorithmInputError("Strassen leaf size must be positive")
    rows, shared = a.shape
    cols = b.shape[1]
    width = _next_power_of_two(max(rows, shared, cols, 1))
    padded_left = np.zeros((width, width), dtype=np.float64)
    padded_right = np.zeros((width, width), dtype=np.float64)
    padded_left[:rows, :shared] = a
    padded_right[:shared, :cols] = b
    product = _strassen(padded_left, padded_right, leaf)
    return product[:rows, :cols]


def _next_power_of_two(value: int) -> int:
    power = 1
    while power < value:
        power *= 2
    return power


def _strassen(left: np.ndarray, right: np.ndarray, leaf: int) -> np.ndarray:
    width = int(left.shape[0])
    if width <= leaf:
        return left @ right
    half = width // 2
    a11, a12 = left[:half, :half], left[:half, half:]
    a21, a22 = left[half:, :half], left[half:, half:]
    b11, b12 = right[:half, :half], right[:half, half:]
    b21, b22 = right[half:, :half], right[half:, half:]
    m1 = _strassen(a11 + a22, b11 + b22, leaf)
    m2 = _strassen(a21 + a22, b11, leaf)
    m3 = _strassen(a11, b12 - b22, leaf)
    m4 = _strassen(a22, b21 - b11, leaf)
    m5 = _strassen(a11 + a12, b22, leaf)
    m6 = _strassen(a21 - a11, b11 + b12, leaf)
    m7 = _strassen(a12 - a22, b21 + b22, leaf)
    product = np.empty((width, width), dtype=np.float64)
    product[:half, :half] = m1 + m4 - m5 + m7
    product[:half, half:] = m3 + m5
    product[half:, :half] = m2 + m4
    product[half:, half:] = m1 - m2 + m3 + m6
    return product
