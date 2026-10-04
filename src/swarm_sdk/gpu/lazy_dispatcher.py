"""Lazy OpenCL vector compute dispatcher with automatic CPU fallback.

Defers pyopencl import and OpenCL context/kernel compilation until batch
threshold is exceeded, keeping CLI startup RSS <40 MB.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

_LOCAL_SIZE_CAP = 64
_DISCRETE_HINTS = ("radeon", "amd", "nvidia", "geforce", "quadro", "arc")

_KERNEL_SOURCE = r"""
__kernel void batch_dot_kernel(__global const float *a,
                               __global const float *b,
                               __global float *out,
                               const uint rows,
                               const uint cols,
                               const uint b_stride_row) {
    __local float partial[64];
    uint r = get_global_id(0);
    uint l = get_local_id(1);
    uint wgs = get_local_size(1);
    if (r >= rows) return;
    float sum = 0.0f;
    size_t a_offset = (size_t)r * cols;
    size_t b_offset = (size_t)r * b_stride_row;
    for (uint c = l; c < cols; c += wgs) {
        sum += a[a_offset + c] * b[b_offset + c];
    }
    partial[l] = sum;
    barrier(CLK_LOCAL_MEM_FENCE);
    for (uint off = wgs >> 1; off > 0; off >>= 1) {
        if (l < off) partial[l] += partial[l + off];
        barrier(CLK_LOCAL_MEM_FENCE);
    }
    if (l == 0) out[r] = partial[0];
}

__kernel void batch_dot4_kernel(__global const float4 *a,
                                __global const float4 *b,
                                __global float *out,
                                const uint rows,
                                const uint vcols,
                                const uint b_stride_row) {
    __local float partial[64];
    uint r = get_global_id(0);
    uint l = get_local_id(1);
    uint wgs = get_local_size(1);
    if (r >= rows) return;
    float4 acc = (float4)(0.0f, 0.0f, 0.0f, 0.0f);
    size_t a_offset = (size_t)r * vcols;
    size_t b_offset = (size_t)r * b_stride_row;
    for (uint c = l; c < vcols; c += wgs) {
        acc += a[a_offset + c] * b[b_offset + c];
    }
    partial[l] = acc.x + acc.y + acc.z + acc.w;
    barrier(CLK_LOCAL_MEM_FENCE);
    for (uint off = wgs >> 1; off > 0; off >>= 1) {
        if (l < off) partial[l] += partial[l + off];
        barrier(CLK_LOCAL_MEM_FENCE);
    }
    if (l == 0) out[r] = partial[0];
}
"""


def _device_rank(device: Any) -> tuple[int, int]:
    """Rank discrete GPUs first, then largest dedicated global memory."""
    name = device.name.lower()
    discrete = 0 if any(hint in name for hint in _DISCRETE_HINTS) else 1
    return (discrete, -int(device.global_mem_size))


def _wgs_for(width: int, max_wg: int) -> int:
    """Largest power of two work-group width that fits the cap and the device."""
    cap = max(1, min(_LOCAL_SIZE_CAP, max_wg))
    wgs = 1
    while wgs * 2 <= width and wgs * 2 <= cap:
        wgs *= 2
    return wgs


class VectorComputeDispatcher:
    """Adaptive vector compute dispatcher with lazy OpenCL loading and CPU fallback."""

    def __init__(self, batch_threshold: int = 1000) -> None:
        """Configure the dispatcher; OpenCL is only initialised once a batch is large enough."""
        self.batch_threshold = batch_threshold
        self._cl_module: Any | None = None
        self._cl_load_failed: bool = False
        self._cl_init_attempted: bool = False
        self._is_lazy_loaded: bool = False
        self._opencl_ready: bool = False
        self._ctx: Any | None = None
        self._queue: Any | None = None
        self._program: Any | None = None
        self._kernel: Any | None = None
        self._kernel4: Any | None = None
        self._max_wg: int = 1
        self._device_name: str = ""

    @property
    def is_lazy_loaded(self) -> bool:
        """True if the OpenCL backend module and context have been lazy loaded."""
        return self._is_lazy_loaded

    def _get_opencl(self) -> Any | None:
        """Lazily import and resolve the pyopencl module."""
        if self._cl_module is not None:
            return self._cl_module
        if self._cl_load_failed:
            return None
        try:
            import pyopencl as cl

            self._cl_module = cl
            return self._cl_module
        except Exception as exc:
            logger.debug("pyopencl import unavailable: %s", exc)
            self._cl_load_failed = True
            return None

    def _ensure_opencl(self) -> bool:
        """Initialize OpenCL context, command queue, and kernels on demand."""
        self._cl_init_attempted = True
        cl = self._get_opencl()
        if cl is None:
            self._opencl_ready = False
            return False

        try:
            preferred = os.environ.get("SWARM_OPENCL_DEVICE", "").strip().lower()
            gpu_devices = [
                device
                for platform in cl.get_platforms()
                for device in platform.get_devices(device_type=cl.device_type.GPU)
            ]

            selected_device = None
            if preferred and gpu_devices:
                selected_device = next(
                    (dev for dev in gpu_devices if preferred in dev.name.lower()),
                    None,
                )
            if selected_device is None and gpu_devices:
                selected_device = min(gpu_devices, key=_device_rank)

            if selected_device is not None:
                self._ctx = cl.Context([selected_device])
            else:
                for platform in cl.get_platforms():
                    cpus = platform.get_devices(device_type=cl.device_type.CPU)
                    if cpus:
                        self._ctx = cl.Context(cpus)
                        break

            if self._ctx is None:
                self._opencl_ready = False
                return False

            device = self._ctx.devices[0]
            self._queue = cl.CommandQueue(self._ctx)
            self._program = cl.Program(self._ctx, _KERNEL_SOURCE).build()
            self._kernel = cl.Kernel(self._program, "batch_dot_kernel")
            self._kernel4 = cl.Kernel(self._program, "batch_dot4_kernel")
            self._max_wg = int(device.max_work_group_size)
            self._device_name = device.name.strip()
            self._opencl_ready = True
            self._is_lazy_loaded = True
            logger.debug("VectorComputeDispatcher OpenCL initialized on %s", self._device_name)
            return True
        except Exception as exc:
            logger.warning("OpenCL initialization failed, falling back to CPU: %s", exc)
            self._opencl_ready = False
            return False

    def compute_dot_product(self, vec_a: np.ndarray, vec_b: np.ndarray) -> float:
        """Compute single vector dot product on CPU (optimized with AVX2 via NumPy)."""
        a = np.asarray(vec_a, dtype=np.float32).reshape(-1)
        b = np.asarray(vec_b, dtype=np.float32).reshape(-1)
        if a.shape[0] != b.shape[0]:
            raise ValueError(f"Vector dimension mismatch: {a.shape[0]} vs {b.shape[0]}")
        return float(np.dot(a, b))

    def _cpu_batch_dot(self, matrix_a: np.ndarray, matrix_b: np.ndarray) -> np.ndarray:
        """Vectorized CPU dot product using NumPy AVX2 path."""
        a = np.asarray(matrix_a, dtype=np.float32)
        b = np.asarray(matrix_b, dtype=np.float32)

        if a.ndim == 1 and b.ndim == 1:
            return np.array([float(np.dot(a, b))], dtype=np.float32)
        if a.ndim == 1:
            return (b @ a).astype(np.float32)
        if b.ndim == 1:
            return (a @ b).astype(np.float32)
        if a.shape[0] == 1 and b.shape[0] > 1:
            return (b @ a[0]).astype(np.float32)
        if b.shape[0] == 1 and a.shape[0] > 1:
            return (a @ b[0]).astype(np.float32)

        return np.einsum("ij,ij->i", a, b, dtype=np.float32)

    def _run_opencl_batch_dot(self, matrix_a: np.ndarray, matrix_b: np.ndarray) -> np.ndarray:
        """Execute OpenCL batch dot product kernel."""
        cl = self._cl_module
        if cl is None or not self._opencl_ready:
            raise RuntimeError("OpenCL is not ready")

        a = np.asarray(matrix_a, dtype=np.float32, order="C")
        b = np.asarray(matrix_b, dtype=np.float32, order="C")
        if not a.flags.c_contiguous:
            a = np.ascontiguousarray(a)
        if not b.flags.c_contiguous:
            b = np.ascontiguousarray(b)

        # Handle broadcasting if one matrix is 1D or single row
        if a.ndim == 1:
            a = a.reshape(1, -1)
        if b.ndim == 1:
            b = b.reshape(1, -1)

        # If a is single-row query and b is batch, swap for row-wise dispatch
        if a.shape[0] == 1 and b.shape[0] > 1:
            a, b = b, a

        rows, cols = a.shape
        is_broadcast_b = b.shape[0] == 1

        queue, kernel, kernel4 = self._queue, self._kernel, self._kernel4
        if queue is None or kernel is None or kernel4 is None:
            raise RuntimeError("OpenCL backend is not initialised")

        mf = cl.mem_flags
        buf_a = cl.Buffer(self._ctx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=a)
        buf_b = cl.Buffer(self._ctx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=b)
        out = np.empty(rows, dtype=np.float32)
        buf_out = cl.Buffer(self._ctx, mf.WRITE_ONLY, out.nbytes)

        if cols % 4 == 0 and cols >= 4:
            vcols = cols // 4
            wgs = _wgs_for(vcols, self._max_wg)
            b_stride = 0 if is_broadcast_b else vcols
            kernel4(
                queue,
                (rows, wgs),
                (1, wgs),
                buf_a,
                buf_b,
                buf_out,
                np.uint32(rows),
                np.uint32(vcols),
                np.uint32(b_stride),
            )
        else:
            wgs = _wgs_for(cols, self._max_wg)
            b_stride = 0 if is_broadcast_b else cols
            kernel(
                queue,
                (rows, wgs),
                (1, wgs),
                buf_a,
                buf_b,
                buf_out,
                np.uint32(rows),
                np.uint32(cols),
                np.uint32(b_stride),
            )

        cl.enqueue_copy(queue, out, buf_out)
        queue.finish()
        return out

    def compute_batch_dot_product(self, matrix_a: np.ndarray, matrix_b: np.ndarray) -> np.ndarray:
        """Batch dot product with dynamic routing: CPU for small, OpenCL for large."""
        a = np.asarray(matrix_a, dtype=np.float32)
        b = np.asarray(matrix_b, dtype=np.float32)

        # Validate feature dimension (last axis)
        dim_a = a.shape[-1]
        dim_b = b.shape[-1]
        if dim_a != dim_b:
            raise ValueError(f"Feature dimension mismatch: {dim_a} vs {dim_b}")

        # Determine total vector pairs
        if a.ndim == 1 and b.ndim == 1:
            total_pairs = 1
        elif a.ndim == 1:
            total_pairs = b.shape[0]
        elif b.ndim == 1:
            total_pairs = a.shape[0]
        elif a.shape[0] == 1:
            total_pairs = b.shape[0]
        elif b.shape[0] == 1:
            total_pairs = a.shape[0]
        else:
            if a.shape[0] != b.shape[0]:
                raise ValueError(f"Batch dimension mismatch: {a.shape[0]} vs {b.shape[0]}")
            total_pairs = a.shape[0]

        # Route to CPU if pairs < threshold
        if total_pairs < self.batch_threshold:
            return self._cpu_batch_dot(a, b)

        # Large batch: attempt OpenCL execution
        if not self._is_lazy_loaded and not self._cl_init_attempted:
            self._ensure_opencl()

        if self._opencl_ready:
            try:
                return self._run_opencl_batch_dot(a, b)
            except Exception as exc:
                logger.warning("OpenCL batch dot failed (%s), falling back to CPU", exc)

        return self._cpu_batch_dot(a, b)

    def get_device_info(self) -> dict[str, Any]:
        """Return active device name, backend type, and lazy loaded status."""
        if not self._is_lazy_loaded and not self._cl_init_attempted:
            self._ensure_opencl()

        if self._opencl_ready and self._device_name:
            clean_name = self._device_name.replace(" Compute Engine", "")
            return {
                "device": clean_name,
                "device_name": clean_name,
                "backend": "opencl",
                "backend_type": "opencl",
                "lazy_loaded": True,
                "is_lazy_loaded": True,
            }

        return {
            "device": "CPU (Host Native AVX2)",
            "device_name": "CPU (Host Native AVX2)",
            "backend": "cpu",
            "backend_type": "cpu",
            "lazy_loaded": False,
            "is_lazy_loaded": False,
        }
