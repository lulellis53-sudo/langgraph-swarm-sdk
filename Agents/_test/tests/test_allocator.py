"""Allocator RSS telemetry reports live, not peak, resident memory."""

from __future__ import annotations

import gc
import sys

import pytest

from swarm_sdk.core.allocator import AllocatorManager

_BLOCK = 256 * 1024 * 1024


@pytest.mark.skipif(
    sys.platform not in {"darwin"} and not sys.platform.startswith("linux"), reason="no live RSS"
)
def test_rss_drops_after_memory_is_released() -> None:
    block = bytearray(_BLOCK)
    block[::4096] = bytes(len(block[::4096]))  # touch every page
    high = AllocatorManager.get_rss_bytes()
    del block
    gc.collect()
    low = AllocatorManager.get_rss_bytes()
    assert high - low > _BLOCK // 2, "RSS must fall after release (peak RSS never would)"
