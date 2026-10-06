"""Compute: OpenCL/NumPy vector dispatcher; scalar scoring lives in ``compute.scoring``.

All functions accept and return NumPy arrays; callers do not need to know
whether the operation ran on the GPU.
"""

from __future__ import annotations

import numpy as np

from swarm_sdk.compute.lazy_dispatcher import VectorComputeDispatcher
from swarm_sdk.compute.opencl_math import (
    batch_cosine,
    batch_dot,
    batch_softmax,
    binary_dot,
    binary_quantize,
    dequant_dot,
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
from swarm_sdk.compute.report import acceleration_report, print_report

__all__ = [
    "VectorComputeDispatcher",
    "acceleration_report",
    "batch_cosine",
    "batch_dot",
    "batch_softmax",
    "binary_dot",
    "binary_quantize",
    "dequant_dot",
    "is_enabled",
    "l2_norm",
    "normalize",
    "normalize_dot",
    "opencl_available",
    "opencl_status",
    "print_report",
    "quantize_int8",
    "reset_opencl",
    "set_enabled",
    "topk_ip",
]


def cosine_matrix(query: np.ndarray, vectors: np.ndarray) -> np.ndarray:
    """Cosine similarities between one query vector and many vectors."""
    return batch_cosine(query, vectors)


def normalize_gpu(vectors: np.ndarray) -> np.ndarray:
    """L2-normalize many vectors."""
    return normalize(vectors)
