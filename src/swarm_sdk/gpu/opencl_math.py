"""OpenCL-backed vector math with a transparent NumPy fallback.

Kernels are kept intentionally simple: compute-heavy reductions run on the GPU,
and small CPU post-processing (argpartition for top-k) keeps the code portable.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    import pyopencl as cl

logger = logging.getLogger(__name__)

_SOURCE = r"""
__kernel void l2_norm(__global const float *matrix,
                      __global float *out,
                      const uint rows,
                      const uint cols) {
    uint r = get_global_id(0);
    if (r >= rows) return;
    float sum = 0.0f;
    for (uint c = 0; c < cols; c++) {
        float v = matrix[r * cols + c];
        sum += v * v;
    }
    out[r] = sqrt(sum);
}

__kernel void normalize_rows(__global const float *matrix,
                        __global float *out,
                        const uint rows,
                        const uint cols) {
    uint r = get_global_id(0);
    if (r >= rows) return;
    float sum = 0.0f;
    for (uint c = 0; c < cols; c++) {
        float v = matrix[r * cols + c];
        sum += v * v;
    }
    float norm = sqrt(sum);
    float inv = norm > 0.0f ? 1.0f / norm : 0.0f;
    for (uint c = 0; c < cols; c++) {
        out[r * cols + c] = matrix[r * cols + c] * inv;
    }
}

__kernel void batch_dot(__global const float *matrix,
                        __global const float *query,
                        __global float *out,
                        const uint rows,
                        const uint cols) {
    uint r = get_global_id(0);
    if (r >= rows) return;
    float sum = 0.0f;
    for (uint c = 0; c < cols; c++) {
        sum += matrix[r * cols + c] * query[c];
    }
    out[r] = sum;
}

__kernel void normalize_dot(__global const float *matrix,
                            __global const float *query,
                            __global float *out,
                            const uint rows,
                            const uint cols) {
    uint r = get_global_id(0);
    if (r >= rows) return;
    float dot = 0.0f;
    float sq = 0.0f;
    for (uint c = 0; c < cols; c++) {
        float v = matrix[r * cols + c];
        dot += v * query[c];
        sq += v * v;
    }
    out[r] = sq > 0.0f ? dot * rsqrt(sq) : 0.0f;
}

__kernel void dequant_dot(__global const char *codes,
                          __global const float *scales,
                          __global const float *query,
                          __global float *out,
                          const uint rows,
                          const uint cols) {
    uint r = get_global_id(0);
    if (r >= rows) return;
    float sum = 0.0f;
    for (uint c = 0; c < cols; c++) sum += (float)codes[r * cols + c] * query[c];
    out[r] = sum * scales[r];
}

__kernel void binary_dot(__global const uint *bits,
                         __global const uint *query,
                         __global float *out,
                         const uint rows,
                         const uint words,
                         const uint dim) {
    uint r = get_global_id(0);
    if (r >= rows) return;
    uint distance = 0;
    for (uint w = 0; w < words; w++) distance += popcount(bits[r * words + w] ^ query[w]);
    out[r] = (float)dim - (float)distance;
}
"""


class _ClState:
    """Lazily-initialized OpenCL context, queue, and compiled program."""

    def __init__(self) -> None:
        self.ctx: cl.Context | None = None
        self.queue: cl.CommandQueue | None = None
        self.program: cl.Program | None = None
        self._kernels: dict[str, Any] = {}
        self._matrix_cache_key: object | None = None
        self._matrix_cache_shape: tuple[int, ...] = ()
        self._matrix_cache_buffer: Any = None
        self._device_name = ""
        self._error: str | None = None
        self._try_init()

    def _try_init(self) -> None:
        try:
            import pyopencl as cl
        except ImportError as exc:
            self._error = f"pyopencl not installed: {exc}"
            return

        try:
            preferred = os.environ.get("SWARM_OPENCL_DEVICE", "").strip().lower()
            gpu_devices = [
                device
                for platform in cl.get_platforms()
                for device in platform.get_devices(device_type=cl.device_type.GPU)
            ]
            if preferred:
                selected = next(
                    (device for device in gpu_devices if preferred in device.name.lower()),
                    None,
                )
                if selected is None:
                    self._error = f"no OpenCL GPU matched SWARM_OPENCL_DEVICE={preferred!r}"
                    return
                self.ctx = cl.Context([selected])
            elif gpu_devices:
                self.ctx = cl.Context([gpu_devices[0]])
            if self.ctx is None:
                for platform in cl.get_platforms():
                    cpus = platform.get_devices(device_type=cl.device_type.CPU)
                    if cpus:
                        self.ctx = cl.Context(cpus)
                        break
            if self.ctx is None:
                self._error = "no OpenCL device found"
                return

            self.queue = cl.CommandQueue(self.ctx)
            self.program = cl.Program(self.ctx, _SOURCE).build()
            self._kernels = {
                name: cl.Kernel(self.program, name)
                for name in (
                    "l2_norm",
                    "normalize_rows",
                    "batch_dot",
                    "normalize_dot",
                    "dequant_dot",
                    "binary_dot",
                )
            }
            self._device_name = self.ctx.devices[0].name.strip()
            logger.debug("OpenCL ready on %s", self._device_name)
        except Exception as exc:  # noqa: BLE001
            self._error = f"OpenCL init failed: {exc}"
            logger.warning(self._error)

    @property
    def available(self) -> bool:
        return self.program is not None and self.queue is not None

    def _cl(self):
        import pyopencl as cl

        return cl

    def kernel(self, name: str) -> Any:
        """Return the cached kernel object (repeated program lookup is expensive)."""
        return self._kernels[name]


_STATE = _ClState()
_ENABLED = True


def set_enabled(enabled: bool) -> None:
    """Globally enable or disable OpenCL offloading."""
    global _ENABLED
    _ENABLED = enabled


def is_enabled() -> bool:
    return _ENABLED


def opencl_available() -> bool:
    return _STATE.available


def opencl_status() -> dict[str, str]:
    return {
        "available": str(_STATE.available),
        "device": _STATE._device_name or "none",
        "error": _STATE._error or "",
    }


def reset_opencl() -> None:
    """Force a fresh OpenCL probe (useful in tests)."""
    global _STATE
    _STATE = _ClState()


def _ensure_f32_contiguous(array: np.ndarray, name: str) -> np.ndarray:
    arr = np.asarray(array, dtype=np.float32, order="C")
    if not arr.flags.c_contiguous:
        arr = np.ascontiguousarray(arr)
    if arr.size == 0:
        raise ValueError(f"{name} must not be empty")
    return arr


def l2_norm(vectors: np.ndarray) -> np.ndarray:
    """Row-wise L2 norms. Falls back to NumPy."""
    matrix = _ensure_f32_contiguous(vectors, "vectors").reshape(-1, vectors.shape[-1])
    if not _use_gpu(matrix.shape[0]):
        return np.linalg.norm(matrix, axis=1).astype(np.float32)

    cl = _STATE._cl()
    rows, cols = matrix.shape
    out = np.empty(rows, dtype=np.float32)
    mf = cl.mem_flags
    buf_m = cl.Buffer(_STATE.ctx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=matrix)
    buf_o = cl.Buffer(_STATE.ctx, mf.WRITE_ONLY, out.nbytes)
    _STATE.kernel("l2_norm")(
        _STATE.queue, (rows,), None, buf_m, buf_o, np.uint32(rows), np.uint32(cols)
    )
    cl.enqueue_copy(_STATE.queue, out, buf_o)
    _STATE.queue.finish()
    return out


def normalize(vectors: np.ndarray) -> np.ndarray:
    """Row-wise L2 normalization. Falls back to NumPy."""
    matrix = _ensure_f32_contiguous(vectors, "vectors").reshape(-1, vectors.shape[-1])
    if not _use_gpu(matrix.shape[0]):
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        return (matrix / norms).astype(np.float32)

    cl = _STATE._cl()
    rows, cols = matrix.shape
    out = np.empty((rows, cols), dtype=np.float32)
    mf = cl.mem_flags
    buf_m = cl.Buffer(_STATE.ctx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=matrix)
    buf_o = cl.Buffer(_STATE.ctx, mf.WRITE_ONLY, out.nbytes)
    _STATE.kernel("normalize_rows")(
        _STATE.queue, (rows,), None, buf_m, buf_o, np.uint32(rows), np.uint32(cols)
    )
    cl.enqueue_copy(_STATE.queue, out, buf_o)
    _STATE.queue.finish()
    return out


def batch_dot(
    query: np.ndarray,
    vectors: np.ndarray,
    *,
    cache_key: object | None = None,
) -> np.ndarray:
    """Dot product of `query` with every row of `vectors`. Falls back to NumPy."""
    query = _ensure_f32_contiguous(query, "query").reshape(-1)
    matrix = _ensure_f32_contiguous(vectors, "vectors").reshape(-1, query.shape[0])
    if matrix.shape[1] != query.shape[0]:
        raise ValueError("query dimension must match vector columns")
    if not _use_gpu(matrix.shape[0]):
        return matrix @ query

    cl = _STATE._cl()
    rows, cols = matrix.shape
    out = np.empty(rows, dtype=np.float32)
    mf = cl.mem_flags
    if (
        cache_key is not None
        and cache_key == _STATE._matrix_cache_key
        and matrix.shape == _STATE._matrix_cache_shape
        and _STATE._matrix_cache_buffer is not None
    ):
        buf_m = _STATE._matrix_cache_buffer
    else:
        buf_m = cl.Buffer(_STATE.ctx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=matrix)
        if cache_key is not None:
            _STATE._matrix_cache_key = cache_key
            _STATE._matrix_cache_shape = matrix.shape
            _STATE._matrix_cache_buffer = buf_m
    buf_q = cl.Buffer(_STATE.ctx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=query)
    buf_o = cl.Buffer(_STATE.ctx, mf.WRITE_ONLY, out.nbytes)
    _STATE.kernel("batch_dot")(
        _STATE.queue, (rows,), None, buf_m, buf_q, buf_o, np.uint32(rows), np.uint32(cols)
    )
    cl.enqueue_copy(_STATE.queue, out, buf_o)
    _STATE.queue.finish()
    return out


def batch_cosine(query: np.ndarray, vectors: np.ndarray) -> np.ndarray:
    """Cosine similarity of `query` with every row of `vectors`. Falls back to NumPy."""
    query = _ensure_f32_contiguous(query, "query").reshape(-1)
    matrix = _ensure_f32_contiguous(vectors, "vectors").reshape(-1, query.shape[0])
    if not _use_gpu(matrix.shape[0]):
        q_norm = np.linalg.norm(query)
        m_norm = np.linalg.norm(matrix, axis=1)
        q_norm = q_norm if q_norm != 0 else 1.0
        m_norm = np.where(m_norm == 0, 1.0, m_norm)
        return (matrix @ query) / (m_norm * q_norm)

    q_norm = float(np.linalg.norm(query))
    if q_norm == 0.0:
        return np.zeros(matrix.shape[0], dtype=np.float32)
    normalized_query = query / q_norm
    normalized_matrix = normalize(matrix)
    return batch_dot(normalized_query, normalized_matrix)


def _launch(name: str, inputs: list[np.ndarray], rows: int, *scalars: int) -> np.ndarray:
    """Run a one-work-item-per-row kernel and return its float32 output."""
    cl = _STATE._cl()
    mf = cl.mem_flags
    out = np.empty(rows, dtype=np.float32)
    buffers = [cl.Buffer(_STATE.ctx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=a) for a in inputs]
    buf_o = cl.Buffer(_STATE.ctx, mf.WRITE_ONLY, out.nbytes)
    _STATE.kernel(name)(
        _STATE.queue, (rows,), None, *buffers, buf_o, *(np.uint32(v) for v in scalars)
    )
    cl.enqueue_copy(_STATE.queue, out, buf_o)
    _STATE.queue.finish()
    return out


def normalize_dot(query: np.ndarray, vectors: np.ndarray) -> np.ndarray:
    """Cosine of ``query`` with every row in one pass; zero-norm rows score 0."""
    query = _ensure_f32_contiguous(query, "query").reshape(-1)
    matrix = _ensure_f32_contiguous(vectors, "vectors").reshape(-1, query.shape[0])
    query_norm = float(np.linalg.norm(query))
    if query_norm == 0.0:
        return np.zeros(matrix.shape[0], dtype=np.float32)
    query = np.ascontiguousarray(query / query_norm, dtype=np.float32)
    if not _use_gpu(matrix.shape[0]):
        norms = np.linalg.norm(matrix, axis=1)
        dots = matrix @ query
        return np.where(norms > 0, dots / np.where(norms > 0, norms, 1.0), 0.0).astype(np.float32)
    return _launch("normalize_dot", [matrix, query], matrix.shape[0], *matrix.shape)


def quantize_int8(matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Symmetric per-row INT8 quantization: ``scale = max(|row|) / 127``."""
    m = _ensure_f32_contiguous(matrix, "matrix")
    if m.ndim == 1:
        m = m.reshape(1, -1)
    peak = np.abs(m).max(axis=1)
    scales = np.where(peak > 0, peak / 127.0, 1.0).astype(np.float32)
    codes = np.clip(np.rint(m / scales[:, None]), -127, 127).astype(np.int8)
    return codes, scales


def dequant_dot(int8_matrix: np.ndarray, scales: np.ndarray, query: np.ndarray) -> np.ndarray:
    """Scores of ``query`` against INT8 rows without materializing a float32 matrix on the GPU."""
    query = _ensure_f32_contiguous(query, "query").reshape(-1)
    codes = np.ascontiguousarray(int8_matrix, dtype=np.int8).reshape(-1, query.shape[0])
    scale = np.ascontiguousarray(scales, dtype=np.float32).reshape(-1)
    if not _use_gpu(codes.shape[0]):
        return ((codes.astype(np.float32) @ query) * scale).astype(np.float32)
    return _launch("dequant_dot", [codes, scale, query], codes.shape[0], *codes.shape)


def binary_quantize(matrix: np.ndarray) -> np.ndarray:
    """Pack sign bits (``>= 0`` is 1) into ``uint32`` words, 32 columns per word."""
    m = np.asarray(matrix, dtype=np.float32)
    if m.ndim == 1:
        m = m.reshape(1, -1)
    rows, cols = m.shape
    words = (cols + 31) // 32
    padded = np.zeros((rows, words * 32), dtype=np.uint8)
    padded[:, :cols] = m >= 0
    packed = np.packbits(padded.reshape(rows, words, 32), axis=2, bitorder="little")
    return np.ascontiguousarray(packed).view(np.uint32).reshape(rows, words)


def binary_dot(bits_matrix: np.ndarray, query_bits: np.ndarray, *, dim: int) -> np.ndarray:
    """``dim - hamming_distance`` per row; higher means more similar."""
    bits = np.ascontiguousarray(bits_matrix, dtype=np.uint32)
    query = np.ascontiguousarray(query_bits, dtype=np.uint32).reshape(-1)
    if bits.shape[1] != query.shape[0]:
        raise ValueError("query words must match matrix words")
    if _use_gpu(bits.shape[0]):
        return _launch(
            "binary_dot", [bits, query], bits.shape[0], bits.shape[0], bits.shape[1], dim
        )
    xor = np.bitwise_xor(bits, query[None, :])
    distance = np.unpackbits(xor.view(np.uint8), axis=1).sum(axis=1)
    return (dim - distance).astype(np.float32)


def batch_softmax(scores: np.ndarray) -> np.ndarray:
    """Numerically stable softmax over a 1-D score vector."""
    s = np.asarray(scores, dtype=np.float32).reshape(-1)
    if s.size == 0:
        return s
    e = np.exp(s - s.max())
    return (e / e.sum()).astype(np.float32)


def topk_ip(
    query: np.ndarray,
    vectors: np.ndarray,
    k: int,
    *,
    cache_key: object | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Return top-k indices and inner-product scores. Falls back to NumPy."""
    if k < 1:
        return np.array([], dtype=np.int64), np.array([], dtype=np.float32)
    scores = batch_dot(query, vectors, cache_key=cache_key)
    k = min(k, scores.shape[0])
    idx = np.argpartition(scores, -k)[-k:]
    idx = idx[np.argsort(-scores[idx])]
    return idx.astype(np.int64), scores[idx]


def _gpu_threshold() -> int:
    """Minimum row count before GPU offload is worth the transfer overhead."""
    try:
        # Measured on the Radeon Pro 5300M: OpenCL transfers dominate through
        # 4096 x 1024 vectors, so leave smaller searches on NumPy by default.
        return int(os.environ.get("SWARM_OPENCL_MIN_ROWS", "8192"))
    except Exception:  # noqa: BLE001
        return 8192


def _use_gpu(n_rows: int) -> bool:
    return _ENABLED and _STATE.available and n_rows >= _gpu_threshold()
