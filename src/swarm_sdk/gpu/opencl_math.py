"""OpenCL-backed vector math with a transparent NumPy fallback.

Kernels are kept intentionally simple: compute-heavy reductions run on the GPU,
and small CPU post-processing (argpartition for top-k) keeps the code portable.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

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

__kernel void normalize(__global const float *matrix,
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
"""


class _ClState:
    """Lazily-initialized OpenCL context, queue, and compiled program."""

    def __init__(self) -> None:
        self.ctx: cl.Context | None = None
        self.queue: cl.CommandQueue | None = None
        self.program: cl.Program | None = None
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
            for platform in cl.get_platforms():
                gpus = platform.get_devices(device_type=cl.device_type.GPU)
                if gpus:
                    self.ctx = cl.Context(gpus)
                    break
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
    _STATE.program.l2_norm(
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
    _STATE.program.normalize(
        _STATE.queue, (rows,), None, buf_m, buf_o, np.uint32(rows), np.uint32(cols)
    )
    cl.enqueue_copy(_STATE.queue, out, buf_o)
    _STATE.queue.finish()
    return out


def batch_dot(query: np.ndarray, vectors: np.ndarray) -> np.ndarray:
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
    buf_m = cl.Buffer(_STATE.ctx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=matrix)
    buf_q = cl.Buffer(_STATE.ctx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=query)
    buf_o = cl.Buffer(_STATE.ctx, mf.WRITE_ONLY, out.nbytes)
    _STATE.program.batch_dot(
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


def topk_ip(query: np.ndarray, vectors: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    """Return top-k indices and inner-product scores. Falls back to NumPy."""
    if k < 1:
        return np.array([], dtype=np.int64), np.array([], dtype=np.float32)
    scores = batch_dot(query, vectors)
    k = min(k, scores.shape[0])
    idx = np.argpartition(scores, -k)[-k:]
    idx = idx[np.argsort(-scores[idx])]
    return idx.astype(np.int64), scores[idx]


def _gpu_threshold() -> int:
    """Minimum row count before GPU offload is worth the transfer overhead."""
    try:
        return int(os.environ.get("SWARM_OPENCL_MIN_ROWS", "64"))
    except Exception:  # noqa: BLE001
        return 64


def _use_gpu(n_rows: int) -> bool:
    return _ENABLED and _STATE.available and n_rows >= _gpu_threshold()
