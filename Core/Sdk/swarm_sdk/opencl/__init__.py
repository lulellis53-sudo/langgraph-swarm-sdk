"""OpenCL vector math and device helpers (NumPy fallback when GPU is unavailable)."""

from __future__ import annotations

from swarm_sdk.opencl.math import (
    batch_cosine,
    batch_dot,
    batch_softmax,
    binary_dot,
    binary_quantize,
    dequant_dot,
    gpu_threshold,
    is_enabled,
    l2_norm,
    normalize,
    normalize_dot,
    opencl_available,
    opencl_status,
    quantize_int8,
    reset_opencl,
    set_enabled,
    topk_ip,
)
from swarm_sdk.opencl.utils import device_rank, workgroup_size

__all__ = [
    "batch_cosine",
    "batch_dot",
    "batch_softmax",
    "binary_dot",
    "binary_quantize",
    "dequant_dot",
    "device_rank",
    "gpu_threshold",
    "is_enabled",
    "l2_norm",
    "normalize",
    "normalize_dot",
    "opencl_available",
    "opencl_status",
    "quantize_int8",
    "reset_opencl",
    "set_enabled",
    "topk_ip",
    "workgroup_size",
]
