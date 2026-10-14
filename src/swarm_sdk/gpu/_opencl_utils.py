"""Shared helpers for selecting OpenCL devices and workgroup sizes."""

from __future__ import annotations

from typing import Any

_LOCAL_SIZE_CAP = 64
_DISCRETE_HINTS = ("radeon", "amd", "nvidia", "geforce", "quadro", "arc")


def device_rank(device: Any) -> tuple[int, int]:
    """Rank discrete GPUs first, then devices with more global memory."""
    name = device.name.lower()
    discrete = 0 if any(hint in name for hint in _DISCRETE_HINTS) else 1
    return (discrete, -int(device.global_mem_size))


def workgroup_size(width: int, max_workgroup_size: int) -> int:
    """Return the largest supported power of two up to the local-size cap."""
    cap = max(1, min(_LOCAL_SIZE_CAP, max_workgroup_size))
    size = 1
    while size * 2 <= width and size * 2 <= cap:
        size *= 2
    return size
