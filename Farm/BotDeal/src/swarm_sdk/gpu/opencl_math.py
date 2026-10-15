"""OpenCL-backed vector math with a transparent NumPy fallback.

Kernels split each matrix row across a whole work-group (2D NDRange: one row
per group) and use ``float4`` loads when the column count allows it, so the
GPU keeps enough loads in flight to saturate its memory bandwidth. Host-side
post-processing (argpartition for top-k) stays on the CPU to keep the code
portable.

Repeated searches against the same store re-upload the query only: chunk
buffers are cached on the device and invalidated through the caller's
``cache_key`` (store token + generation + chunk range).
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    import pyopencl as cl

logger = logging.getLogger(__name__)

_LOCAL_SIZE_CAP = 64
_BUF_CACHE_MAX_ENTRIES = 32
_BUF_CACHE_MAX_BYTES = 256 * 1024 * 1024

_SOURCE = r"""
__kernel void l2_norm2d(__global const float *matrix,
                        __global float *out,
                        const uint rows,
                        const uint cols) {
    __local float partial[64];
    uint r = get_global_id(0);
    uint l = get_local_id(1);
    uint wgs = get_local_size(1);
    if (r >= rows) return;
    float sum = 0.0f;
    for (uint c = l; c < cols; c += wgs) {
        float v = matrix[(size_t)r * cols + c];
        sum += v * v;
    }
    partial[l] = sum;
    barrier(CLK_LOCAL_MEM_FENCE);
    for (uint off = wgs >> 1; off > 0; off >>= 1) {
        if (l < off) partial[l] += partial[l + off];
        barrier(CLK_LOCAL_MEM_FENCE);
    }
    if (l == 0) out[r] = sqrt(partial[0]);
}

__kernel void norm_rows2d(__global const float *matrix,
                          __global float *out,
                          const uint rows,
                          const uint cols) {
    __local float partial[64];
    uint r = get_global_id(0);
    uint l = get_local_id(1);
    uint wgs = get_local_size(1);
    if (r >= rows) return;
    float sum = 0.0f;
    for (uint c = l; c < cols; c += wgs) {
        float v = matrix[(size_t)r * cols + c];
        sum += v * v;
    }
    partial[l] = sum;
    barrier(CLK_LOCAL_MEM_FENCE);
    for (uint off = wgs >> 1; off > 0; off >>= 1) {
        if (l < off) partial[l] += partial[l + off];
        barrier(CLK_LOCAL_MEM_FENCE);
    }
    if (l == 0) partial[0] = partial[0] > 0.0f ? 1.0f / sqrt(partial[0]) : 0.0f;
    barrier(CLK_LOCAL_MEM_FENCE);
    float inv = partial[0];
    for (uint c = l; c < cols; c += wgs) {
        out[(size_t)r * cols + c] = matrix[(size_t)r * cols + c] * inv;
    }
}

__kernel void dot2d(__global const float *matrix,
                    __global const float *query,
                    __global float *out,
                    const uint rows,
                    const uint cols) {
    __local float partial[64];
    uint r = get_global_id(0);
    uint l = get_local_id(1);
    uint wgs = get_local_size(1);
    if (r >= rows) return;
    float sum = 0.0f;
    for (uint c = l; c < cols; c += wgs) {
        sum += matrix[(size_t)r * cols + c] * query[c];
    }
    partial[l] = sum;
    barrier(CLK_LOCAL_MEM_FENCE);
    for (uint off = wgs >> 1; off > 0; off >>= 1) {
        if (l < off) partial[l] += partial[l + off];
        barrier(CLK_LOCAL_MEM_FENCE);
    }
    if (l == 0) out[r] = partial[0];
}

__kernel void dot2d4(__global const float4 *matrix,
                     __global const float4 *query,
                     __global float *out,
                     const uint rows,
                     const uint vcols) {
    __local float partial[64];
    uint r = get_global_id(0);
    uint l = get_local_id(1);
    uint wgs = get_local_size(1);
    if (r >= rows) return;
    float4 acc = (float4)(0.0f, 0.0f, 0.0f, 0.0f);
    for (uint c = l; c < vcols; c += wgs) {
        acc += matrix[(size_t)r * vcols + c] * query[c];
    }
    partial[l] = acc.x + acc.y + acc.z + acc.w;
    barrier(CLK_LOCAL_MEM_FENCE);
    for (uint off = wgs >> 1; off > 0; off >>= 1) {
        if (l < off) partial[l] += partial[l + off];
        barrier(CLK_LOCAL_MEM_FENCE);
    }
    if (l == 0) out[r] = partial[0];
}

__kernel void normdot2d(__global const float *matrix,
                        __global const float *query,
                        __global float *out,
                        const uint rows,
                        const uint cols) {
    __local float part_dot[64];
    __local float part_sq[64];
    uint r = get_global_id(0);
    uint l = get_local_id(1);
    uint wgs = get_local_size(1);
    if (r >= rows) return;
    float dot = 0.0f;
    float sq = 0.0f;
    for (uint c = l; c < cols; c += wgs) {
        float v = matrix[(size_t)r * cols + c];
        dot += v * query[c];
        sq += v * v;
    }
    part_dot[l] = dot;
    part_sq[l] = sq;
    barrier(CLK_LOCAL_MEM_FENCE);
    for (uint off = wgs >> 1; off > 0; off >>= 1) {
        if (l < off) {
            part_dot[l] += part_dot[l + off];
            part_sq[l] += part_sq[l + off];
        }
        barrier(CLK_LOCAL_MEM_FENCE);
    }
    if (l == 0) out[r] = part_sq[0] > 0.0f ? part_dot[0] * rsqrt(part_sq[0]) : 0.0f;
}

__kernel void normdot2d4(__global const float4 *matrix,
                         __global const float4 *query,
                         __global float *out,
                         const uint rows,
                         const uint vcols) {
    __local float part_dot[64];
    __local float part_sq[64];
    uint r = get_global_id(0);
    uint l = get_local_id(1);
    uint wgs = get_local_size(1);
    if (r >= rows) return;
    float4 accd = (float4)(0.0f, 0.0f, 0.0f, 0.0f);
    float4 accs = (float4)(0.0f, 0.0f, 0.0f, 0.0f);
    for (uint c = l; c < vcols; c += wgs) {
        float4 v = matrix[(size_t)r * vcols + c];
        accd += v * query[c];
        accs += v * v;
    }
    part_dot[l] = accd.x + accd.y + accd.z + accd.w;
    part_sq[l] = accs.x + accs.y + accs.z + accs.w;
    barrier(CLK_LOCAL_MEM_FENCE);
    for (uint off = wgs >> 1; off > 0; off >>= 1) {
        if (l < off) {
            part_dot[l] += part_dot[l + off];
            part_sq[l] += part_sq[l + off];
        }
        barrier(CLK_LOCAL_MEM_FENCE);
    }
    if (l == 0) out[r] = part_sq[0] > 0.0f ? part_dot[0] * rsqrt(part_sq[0]) : 0.0f;
}

__kernel void dq2d(__global const char *codes,
                   __global const float *scales,
                   __global const float *query,
                   __global float *out,
                   const uint rows,
                   const uint cols) {
    __local float partial[64];
    uint r = get_global_id(0);
    uint l = get_local_id(1);
    uint wgs = get_local_size(1);
    if (r >= rows) return;
    float sum = 0.0f;
    for (uint c = l; c < cols; c += wgs) {
        sum += (float)codes[(size_t)r * cols + c] * query[c];
    }
    partial[l] = sum;
    barrier(CLK_LOCAL_MEM_FENCE);
    for (uint off = wgs >> 1; off > 0; off >>= 1) {
        if (l < off) partial[l] += partial[l + off];
        barrier(CLK_LOCAL_MEM_FENCE);
    }
    if (l == 0) out[r] = partial[0] * scales[r];
}

__kernel void bdot2d(__global const uint *bits,
                     __global const uint *query,
                     __global float *out,
                     const uint rows,
                     const uint words,
                     const uint dim) {
    __local uint partial[64];
    uint r = get_global_id(0);
    uint l = get_local_id(1);
    uint wgs = get_local_size(1);
    if (r >= rows) return;
    uint distance = 0;
    for (uint w = l; w < words; w += wgs) {
        distance += popcount(bits[(size_t)r * words + w] ^ query[w]);
    }
    partial[l] = distance;
    barrier(CLK_LOCAL_MEM_FENCE);
    for (uint off = wgs >> 1; off > 0; off >>= 1) {
        if (l < off) partial[l] += partial[l + off];
        barrier(CLK_LOCAL_MEM_FENCE);
    }
    if (l == 0) out[r] = (float)dim - (float)partial[0];
}
"""

_DISCRETE_HINTS = ("radeon", "amd", "nvidia", "geforce", "quadro", "arc")


def _device_rank(device: Any) -> tuple[int, int]:
    """Discrete GPUs first, then the largest dedicated memory."""
    name = device.name.lower()
    discrete = 0 if any(hint in name for hint in _DISCRETE_HINTS) else 1
    return (discrete, -int(device.global_mem_size))


class _ClState:
    """Lazily-initialized OpenCL context, queue, and compiled program."""

    def __init__(self) -> None:
        self.ctx: cl.Context | None = None
        self.queue: cl.CommandQueue | None = None
        self.program: cl.Program | None = None
        self._kernels: dict[str, Any] = {}
        self._max_wg = 1
        self._device_name = ""
        self._error: str | None = None
        self._buf_cache: dict[object, tuple[tuple[tuple[int, ...], ...], list[Any], int]] = {}
        self._buf_cache_bytes = 0
        self._initialized = False

    def _ensure_init(self) -> None:
        if not self._initialized:
            self._initialized = True
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
                self.ctx = cl.Context([min(gpu_devices, key=_device_rank)])
            if self.ctx is None:
                for platform in cl.get_platforms():
                    cpus = platform.get_devices(device_type=cl.device_type.CPU)
                    if cpus:
                        self.ctx = cl.Context(cpus)
                        break
            if self.ctx is None:
                self._error = "no OpenCL device found"
                return

            device = self.ctx.devices[0]
            self.queue = cl.CommandQueue(self.ctx)
            self.program = cl.Program(self.ctx, _SOURCE).build()
            self._kernels = {
                name: cl.Kernel(self.program, name)
                for name in (
                    "l2_norm2d",
                    "norm_rows2d",
                    "dot2d",
                    "dot2d4",
                    "normdot2d",
                    "normdot2d4",
                    "dq2d",
                    "bdot2d",
                )
            }
            self._max_wg = int(device.max_work_group_size)
            self._device_name = device.name.strip()
            logger.debug("OpenCL ready on %s", self._device_name)
        except Exception as exc:  # noqa: BLE001
            self._error = f"OpenCL init failed: {exc}"
            logger.warning(self._error)

    @property
    def available(self) -> bool:
        """Whether an OpenCL context is ready."""
        self._ensure_init()
        return self.program is not None and self.queue is not None

    def _cl(self):
        import pyopencl as cl

        return cl

    @property
    def context(self) -> cl.Context:
        """The OpenCL context (initialized on first access)."""
        if self.ctx is None:
            raise RuntimeError("OpenCL context is unavailable")
        return self.ctx

    @property
    def cmd_queue(self) -> cl.CommandQueue:
        """The command queue for kernel dispatch."""
        if self.queue is None:
            raise RuntimeError("OpenCL command queue is unavailable")
        return self.queue

    def kernel(self, name: str) -> Any:
        """Return the cached kernel object (repeated program lookup is expensive)."""
        return self._kernels[name]

    def cached_buffers(self, cache_key: object, arrays: list[np.ndarray]) -> list[Any]:
        """Device buffers for ``arrays``, reused while ``cache_key`` stays the same."""
        shapes = tuple(a.shape for a in arrays)
        hit = self._buf_cache.get(cache_key)
        if hit is not None and hit[0] == shapes:
            return hit[1]
        cl = self._cl()
        mf = cl.mem_flags
        buffers = [
            cl.Buffer(self.context, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=array)
            for array in arrays
        ]
        if cache_key is not None:
            payload = sum(int(a.nbytes) for a in arrays)
            while self._buf_cache and (
                len(self._buf_cache) >= _BUF_CACHE_MAX_ENTRIES
                or self._buf_cache_bytes + payload > _BUF_CACHE_MAX_BYTES
            ):
                oldest = next(iter(self._buf_cache))
                _, _, dropped = self._buf_cache.pop(oldest)
                self._buf_cache_bytes -= dropped
            self._buf_cache[cache_key] = (shapes, buffers, payload)
            self._buf_cache_bytes += payload
        return buffers


_STATE = _ClState()
_ENABLED = True


def set_enabled(enabled: bool) -> None:
    """Globally enable or disable OpenCL offloading."""
    global _ENABLED
    _ENABLED = enabled


def is_enabled() -> bool:
    """Whether GPU math is enabled (``SWARM_GPU_BACKEND``)."""
    return _ENABLED


def opencl_available() -> bool:
    """Whether pyopencl and a usable device are present."""
    return _STATE.available


def opencl_status() -> dict[str, str]:
    """One-line GPU status for diagnostics."""
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


def _wgs_for(width: int) -> int:
    """Largest power of two work-group width that fits the cap and the device."""
    cap = max(1, min(_LOCAL_SIZE_CAP, _STATE._max_wg))
    wgs = 1
    while wgs * 2 <= width and wgs * 2 <= cap:
        wgs *= 2
    return wgs


def _run2d(name: str, buffers: list[Any], rows: int, wgs: int, *scalars: int) -> np.ndarray:
    """Run a rows-x-workgroup kernel and return its float32 output."""
    cl = _STATE._cl()
    mf = cl.mem_flags
    out = np.empty(rows, dtype=np.float32)
    buf_o = cl.Buffer(_STATE.context, mf.WRITE_ONLY, out.nbytes)
    _STATE.kernel(name)(
        _STATE.cmd_queue,
        (rows, wgs),
        (1, wgs),
        *buffers,
        buf_o,
        *(np.uint32(v) for v in scalars),
    )
    cl.enqueue_copy(_STATE.cmd_queue, out, buf_o)
    _STATE.cmd_queue.finish()
    return out


def l2_norm(vectors: np.ndarray) -> np.ndarray:
    r"""Row-wise L2 (Euclidean) norms. Falls back to NumPy.

    .. math::
        \|x_i\|_2 = \sqrt{\sum_j x_{ij}^2}
    """
    matrix = _ensure_f32_contiguous(vectors, "vectors").reshape(-1, vectors.shape[-1])
    if not _use_gpu(matrix.shape[0]):
        return np.linalg.norm(matrix, axis=1).astype(np.float32)

    rows, cols = matrix.shape
    buffers = _STATE.cached_buffers(None, [matrix])
    return _run2d("l2_norm2d", buffers, rows, _wgs_for(cols), rows, cols)


def normalize(vectors: np.ndarray) -> np.ndarray:
    r"""Row-wise L2 normalization. Falls back to NumPy.

    .. math::
        \hat{x}_i = \frac{x_i}{\|x_i\|_2}

    Zero rows are returned unchanged.
    """
    matrix = _ensure_f32_contiguous(vectors, "vectors").reshape(-1, vectors.shape[-1])
    if not _use_gpu(matrix.shape[0]):
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        return (matrix / norms).astype(np.float32)

    rows, cols = matrix.shape
    cl = _STATE._cl()
    mf = cl.mem_flags
    out = np.empty((rows, cols), dtype=np.float32)
    buf_m = cl.Buffer(_STATE.context, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=matrix)
    buf_o = cl.Buffer(_STATE.context, mf.WRITE_ONLY, out.nbytes)
    _STATE.kernel("norm_rows2d")(
        _STATE.cmd_queue,
        (rows, _wgs_for(cols)),
        (1, _wgs_for(cols)),
        buf_m,
        buf_o,
        np.uint32(rows),
        np.uint32(cols),
    )
    cl.enqueue_copy(_STATE.cmd_queue, out, buf_o)
    _STATE.cmd_queue.finish()
    return out


def batch_dot(
    query: np.ndarray,
    vectors: np.ndarray,
    *,
    cache_key: object | None = None,
) -> np.ndarray:
    r"""Dot product of ``query`` with every row of ``vectors``. Falls back to NumPy.

    .. math::
        s_i = \sum_j q_j \cdot v_{ij}
    """
    query = _ensure_f32_contiguous(query, "query").reshape(-1)
    matrix = _ensure_f32_contiguous(vectors, "vectors").reshape(-1, query.shape[0])
    if matrix.shape[1] != query.shape[0]:
        raise ValueError("query dimension must match vector columns")
    if not _use_gpu(matrix.shape[0]):
        return matrix @ query

    rows, cols = matrix.shape
    cl = _STATE._cl()
    mf = cl.mem_flags
    buf_m = _STATE.cached_buffers(cache_key, [matrix])[0]
    buf_q = cl.Buffer(_STATE.context, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=query)
    if cols % 4 == 0:
        return _run2d("dot2d4", [buf_m, buf_q], rows, _wgs_for(cols), rows, cols // 4)
    return _run2d("dot2d", [buf_m, buf_q], rows, _wgs_for(cols), rows, cols)


def batch_cosine(query: np.ndarray, vectors: np.ndarray) -> np.ndarray:
    r"""Cosine similarity of ``query`` with every row of ``vectors``. Falls back to NumPy.

    .. math::
        \operatorname{cos}(q, v_i) = \frac{q \cdot v_i}{\|q\|_2 \cdot \|v_i\|_2}
    """
    query = _ensure_f32_contiguous(query, "query").reshape(-1)
    matrix = _ensure_f32_contiguous(vectors, "vectors").reshape(-1, query.shape[0])
    if not _use_gpu(matrix.shape[0]):
        q_norm = np.linalg.norm(query)
        m_norm = np.linalg.norm(matrix, axis=1)
        q_norm = q_norm if q_norm != 0 else 1.0
        m_norm = np.where(m_norm == 0, 1.0, m_norm)
        return (matrix @ query) / (m_norm * q_norm)

    return normalize_dot(query, matrix)


def normalize_dot(query: np.ndarray, vectors: np.ndarray) -> np.ndarray:
    r"""Cosine of ``query`` with every row in one pass; zero-norm rows score 0.

    .. math::
        \operatorname{cos}(q, v_i) = \frac{q \cdot v_i}{\|q\|_2 \cdot \|v_i\|_2}

    The query is normalized once on the host; the kernel computes the row
    norms and divides in a single pass.
    """
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

    rows, cols = matrix.shape
    cl = _STATE._cl()
    mf = cl.mem_flags
    buf_m = cl.Buffer(_STATE.context, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=matrix)
    buf_q = cl.Buffer(_STATE.context, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=query)
    wgs = _wgs_for(cols)
    if cols % 4 == 0:
        return _run2d("normdot2d4", [buf_m, buf_q], rows, wgs, rows, cols // 4)
    return _run2d("normdot2d", [buf_m, buf_q], rows, wgs, rows, cols)


def quantize_int8(matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    r"""Symmetric per-row INT8 quantization.

    .. math::
        \operatorname{scale}_i = \frac{\max_j |x_{ij}|}{127}

    .. math::
        q_{ij} = \operatorname{clip}\!\left(\operatorname{round}\!
            \left(\frac{x_{ij}}{\operatorname{scale}_i}\right), -127, 127\right)

    When :math:`\max_j |x_{ij}| = 0`, the scale is defined as ``1.0`` so the
    zero row stays zero after dequantization.
    """
    m = _ensure_f32_contiguous(matrix, "matrix")
    if m.ndim == 1:
        m = m.reshape(1, -1)
    peak = np.abs(m).max(axis=1)
    scales = np.where(peak > 0, peak / 127.0, 1.0).astype(np.float32)
    codes = np.clip(np.rint(m / scales[:, None]), -127, 127).astype(np.int8)
    return codes, scales


def dequant_dot(
    int8_matrix: np.ndarray,
    scales: np.ndarray,
    query: np.ndarray,
    *,
    cache_key: object | None = None,
) -> np.ndarray:
    r"""Scores of ``query`` against INT8 rows without materializing a float32 matrix on the GPU.

    .. math::
        s_i = \operatorname{scale}_i \cdot \sum_j q_j \cdot q_{ij}

    where :math:`q_{ij}` are the INT8 codes and :math:`\operatorname{scale}_i`
    is the per-row float32 scale.
    """
    query = _ensure_f32_contiguous(query, "query").reshape(-1)
    codes = np.ascontiguousarray(int8_matrix, dtype=np.int8).reshape(-1, query.shape[0])
    scale = np.ascontiguousarray(scales, dtype=np.float32).reshape(-1)
    if not _use_gpu(codes.shape[0]):
        return ((codes.astype(np.float32) @ query) * scale).astype(np.float32)

    rows, cols = codes.shape
    cl = _STATE._cl()
    mf = cl.mem_flags
    buf_c, buf_s = _STATE.cached_buffers(cache_key, [codes, scale])
    buf_q = cl.Buffer(_STATE.context, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=query)
    return _run2d("dq2d", [buf_c, buf_s, buf_q], rows, _wgs_for(cols), rows, cols)


def binary_quantize(matrix: np.ndarray) -> np.ndarray:
    r"""Pack sign bits into ``uint32`` words, 32 columns per word.

    Each dimension becomes a binary value:

    .. math::
        b_j = \begin{cases}
            1 & x_j \ge 0 \\
            0 & x_j < 0
        \end{cases}

    The bits are packed little-endian into 32-bit words.
    """
    m = np.asarray(matrix, dtype=np.float32)
    if m.ndim == 1:
        m = m.reshape(1, -1)
    rows, cols = m.shape
    words = (cols + 31) // 32
    padded = np.zeros((rows, words * 32), dtype=np.uint8)
    padded[:, :cols] = m >= 0
    packed = np.packbits(padded.reshape(rows, words, 32), axis=2, bitorder="little")
    return np.ascontiguousarray(packed).view(np.uint32).reshape(rows, words)


def binary_dot(
    bits_matrix: np.ndarray,
    query_bits: np.ndarray,
    *,
    dim: int,
    cache_key: object | None = None,
) -> np.ndarray:
    r"""``dim - hamming_distance`` per row; higher means more similar.

    .. math::
        s_i = \dim - \sum_j \operatorname{popcount}(b_{ij} \oplus q_j)

    where :math:`\oplus` is bitwise XOR. Identical binary vectors score
    ``dim``; opposite vectors score ``0``.
    """
    bits = np.ascontiguousarray(bits_matrix, dtype=np.uint32)
    query = np.ascontiguousarray(query_bits, dtype=np.uint32).reshape(-1)
    if bits.shape[1] != query.shape[0]:
        raise ValueError("query words must match matrix words")
    if _use_gpu(bits.shape[0]):
        rows, words = bits.shape
        buf_b = _STATE.cached_buffers(cache_key, [bits])[0]
        cl = _STATE._cl()
        mf = cl.mem_flags
        buf_q = cl.Buffer(_STATE.context, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=query)
        return _run2d("bdot2d", [buf_b, buf_q], rows, _wgs_for(words), rows, words, dim)
    xor = np.bitwise_xor(bits, query[None, :])
    distance = np.unpackbits(xor.view(np.uint8), axis=1).sum(axis=1)
    return (dim - distance).astype(np.float32)


def batch_softmax(scores: np.ndarray) -> np.ndarray:
    r"""Numerically stable softmax over a 1-D score vector.

    .. math::
        p_i = \frac{e^{s_i - \max_j s_j}}{\sum_j e^{s_j - \max_j s_j}}

    The shift by :math:`\max_j s_j` prevents overflow for large scores.
    """
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
    r"""Return top-k indices and inner-product scores. Falls back to NumPy.

    Computes :math:`s_i = q \cdot v_i`, then returns the ``k`` largest scores
    sorted descending.
    """
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
        # One-shot calls re-upload the matrix every time, which stays slower
        # than NumPy BLAS through at least 8192x1024 on the Radeon Pro 5300M.
        # Repeated searches that keep their chunk buffers resident (the
        # OpenClVecStore cache_key path) win much earlier; lower this via
        # SWARM_OPENCL_MIN_ROWS for serving workloads.
        return int(os.environ.get("SWARM_OPENCL_MIN_ROWS", "8192"))
    except Exception:  # noqa: BLE001
        return 8192


def _use_gpu(n_rows: int) -> bool:
    return _ENABLED and _STATE.available and n_rows >= _gpu_threshold()
