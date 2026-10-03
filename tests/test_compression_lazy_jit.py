"""Tests for Zstd compression, Lifeguard lazy imports, hybrid JIT/NoJIT, and buffer pools."""

from __future__ import annotations

import os
import pytest

from swarm_sdk.core.compression import (
    CompressedScratchpadPool,
    LazyModule,
    ZstdStateCompressor,
    hybrid_jit,
    is_jit_disabled,
    lazy_import,
)
from swarm_sdk.core.minimalloc import Buffer, Configuration, MiniMalloc


class TestLazyImportLifeguard:
    """Test PEP 810 compliant LazyModule proxy."""

    def test_lazy_module_deferred_loading(self) -> None:
        lazy_json = lazy_import("json")
        assert isinstance(lazy_json, LazyModule)
        assert "<LazyModule 'json' (unloaded)>" in repr(lazy_json)

        # Trigger attribute access
        encoded = lazy_json.dumps({"test_key": 42})
        assert encoded == '{"test_key": 42}'
        assert "<LazyModule 'json' (loaded)>" in repr(lazy_json)

    def test_lazy_math_functions(self) -> None:
        lazy_math = lazy_import("math")
        assert lazy_math.sqrt(16.0) == 4.0
        assert lazy_math.pi > 3.14


class TestHybridJitExecution:
    """Test polymorphic hybrid_jit decorator with JIT and NoJIT modes."""

    def test_hybrid_jit_fallback_execution(self) -> None:
        @hybrid_jit(nogil=True, fastmath=True)
        def vector_add(a: list[float], b: list[float]) -> list[float]:
            return [x + y for x, y in zip(a, b)]

        res = vector_add([1.0, 2.0, 3.0], [4.0, 5.0, 6.0])
        assert res == [5.0, 7.0, 9.0]

    def test_hybrid_jit_respects_nojit_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NUMBA_DISABLE_JIT", "1")
        assert is_jit_disabled() is True

        @hybrid_jit(nogil=True)
        def compute_square(x: int) -> int:
            return x * x

        assert getattr(compute_square, "__jit_compiled__", None) is False
        assert compute_square(5) == 25


class TestZstdZeroCopyCompressor:
    """Test Zstandard compression and zero-copy memoryview pipelines."""

    def test_text_compression_ratio(self) -> None:
        compressor = ZstdStateCompressor(level=3)
        assert compressor.backend_name in ("python314_native_zstd", "python_zstandard", "zlib_fallback")

        sample_prompt = "You are an autonomous LangGraph Swarm agent. Execute task cleanly. " * 30
        compressed = compressor.compress_text(sample_prompt)
        assert len(compressed) < len(sample_prompt.encode("utf-8"))
        # High compression ratio (> 5x on repetitive prompts)
        ratio = len(sample_prompt.encode("utf-8")) / len(compressed)
        assert ratio >= 5.0

        recovered = compressor.decompress_text(compressed)
        assert recovered == sample_prompt

    def test_zero_copy_memoryview_compression(self) -> None:
        compressor = ZstdStateCompressor()
        raw_payload = bytearray(b"Zero-copy memoryview tensor buffer state payload " * 40)
        mv = memoryview(raw_payload)

        compressed = compressor.compress(mv)
        assert len(compressed) > 0

        decompressed = compressor.decompress(compressed)
        assert decompressed == raw_payload


class TestCompressedScratchpadPool:
    """Test MiniMalloc static placement coupled with Zstd cold-tier compression."""

    def test_pool_static_packing_and_cold_tier(self) -> None:
        # 1. Use MiniMalloc to plan offsets for 3 buffers
        buffers = [
            Buffer(id="scratch_agent1", lower_time=0, upper_time=4, size=4096),
            Buffer(id="scratch_agent2", lower_time=2, upper_time=6, size=4096),
            Buffer(id="scratch_agent3", lower_time=4, upper_time=8, size=4096),
        ]
        solver = MiniMalloc(Configuration(alignment=32))
        solution = solver.solve(buffers)
        assert solution.verified is True

        # 2. Register into pool
        pool = CompressedScratchpadPool(alignment=32)
        for b in buffers:
            pool.register_buffer(b.id, b.size, solution.offsets[b.id])

        init_fp = pool.get_memory_footprint()
        assert init_fp["active_bytes"] == 12288
        assert init_fp["cold_bytes"] == 0

        # Fill agent1 buffer
        buf1 = pool.entries["scratch_agent1"].raw_buffer
        assert buf1 is not None
        buf1[0:11] = b"HELLO_SWARM"

        # 3. Freeze agent1 to cold tier (agent finished wave)
        compressed_len = pool.freeze_to_cold_tier("scratch_agent1")
        assert compressed_len > 0
        assert pool.entries["scratch_agent1"].is_compressed is True
        assert pool.entries["scratch_agent1"].raw_buffer is None

        cold_fp = pool.get_memory_footprint()
        assert cold_fp["active_bytes"] == 8192  # 4096 released from RAM
        assert cold_fp["cold_bytes"] == compressed_len

        # 4. Restore agent1 from cold tier
        restored = pool.restore_from_cold_tier("scratch_agent1")
        assert restored[0:11] == b"HELLO_SWARM"
        assert pool.entries["scratch_agent1"].is_compressed is False

        restored_fp = pool.get_memory_footprint()
        assert restored_fp["active_bytes"] == 12288
        assert restored_fp["cold_bytes"] == 0
