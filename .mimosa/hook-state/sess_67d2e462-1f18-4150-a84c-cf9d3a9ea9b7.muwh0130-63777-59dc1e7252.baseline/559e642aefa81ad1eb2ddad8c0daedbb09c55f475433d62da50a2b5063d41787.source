"""VRAM budget arithmetic for the 4 GB Radeon Pro 5300M (Molten.md §10.1).

``VRAM_total = model + KV cache + scratch <= budget``; keeping every layer
resident avoids spilling over PCIe into system memory.
"""

from __future__ import annotations

DEFAULT_BUDGET_MIB = 3800
_MIB = 2**20


def kv_cache_mib(
    *,
    n_layers: int,
    n_kv_heads: int,
    d_head: int,
    n_ctx: int,
    bytes_per_element: int = 2,
) -> float:
    """Return the KV-cache size in MiB: ``2 * layers * kv_heads * d_head * ctx * bytes``."""
    if min(n_layers, n_kv_heads, d_head, n_ctx, bytes_per_element) < 1:
        raise ValueError("all KV cache dimensions must be >= 1")
    return 2 * n_layers * n_kv_heads * d_head * n_ctx * bytes_per_element / _MIB


def vram_total_mib(model_mib: float, kv_mib: float, scratch_mib: float = 0.0) -> float:
    """Return the working-set size in MiB."""
    if min(model_mib, kv_mib, scratch_mib) < 0:
        raise ValueError("sizes must be >= 0")
    return model_mib + kv_mib + scratch_mib


def fits_vram(
    model_mib: float,
    kv_mib: float,
    scratch_mib: float = 0.0,
    *,
    budget_mib: float = DEFAULT_BUDGET_MIB,
) -> bool:
    """Return whether the working set fits the budget (inclusive)."""
    return vram_total_mib(model_mib, kv_mib, scratch_mib) <= budget_mib


__all__ = ["DEFAULT_BUDGET_MIB", "fits_vram", "kv_cache_mib", "vram_total_mib"]
