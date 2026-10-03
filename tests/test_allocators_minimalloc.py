"""Tests and benchmarks for AllocatorManager and Google MiniMalloc static buffer solver."""

from __future__ import annotations

import time
import pytest

from swarm_sdk.core.allocator import AllocatorManager, GuardReport, MemoryStats
from swarm_sdk.core.minimalloc import Buffer, Configuration, MiniMalloc, SolverType


class TestAllocatorManager:
    """Test dynamic memory allocator detection and telemetry."""

    def test_allocator_detection(self) -> None:
        manager = AllocatorManager()
        assert isinstance(manager.allocator_name, str)
        assert len(manager.allocator_name) > 0
        stats = manager.get_memory_stats()
        assert isinstance(stats, MemoryStats)
        assert stats.rss_mb > 0.0
        assert stats.rss_gb > 0.0
        assert isinstance(stats.free_threaded, bool)

    def test_allocation_benchmark_throughput(self) -> None:
        manager = AllocatorManager()
        bench = manager.benchmark_allocation(num_ops=50_000, chunk_size=64)
        assert "total_ms" in bench
        assert "ops_per_sec" in bench
        assert "ns_per_op" in bench
        assert bench["total_ms"] > 0.0
        assert bench["ops_per_sec"] > 10_000.0
        assert bench["ns_per_op"] > 0.0

    def test_guard_memory_context_manager(self) -> None:
        """Tests that guard_memory tracks execution telemetry and respects safety ceiling."""
        with AllocatorManager.guard_memory(ceiling_gb=13.6) as guard:
            assert isinstance(guard, GuardReport)
            assert guard.ceiling_gb == 13.6
            # Allocate temporary memory
            temp = [bytearray(1024) for _ in range(100)]
            assert len(temp) == 100

        assert guard.duration_ms >= 0.0
        assert guard.breached is False
        assert guard.final_rss_mb > 0.0

    def test_guard_memory_ceiling_violation_raises(self) -> None:
        """Tests that guard_memory raises MemoryError when ceiling is breached."""
        with pytest.raises(MemoryError, match="Memory ceiling exceeded"):
            with AllocatorManager.guard_memory(ceiling_gb=0.000001):
                pass

    def test_trim_memory_execution(self) -> None:
        """Tests trim_memory cleans unreachable objects without error."""
        trim_res = AllocatorManager.trim_memory()
        assert isinstance(trim_res, dict)
        assert "unreachable_objects_collected" in trim_res
        assert "current_rss_mb" in trim_res
        assert trim_res["current_rss_mb"] > 0.0


class TestMiniMallocStaticCompaction:
    """Test Google MiniMalloc static 2D strip-packing buffer compaction."""

    def test_invalid_buffer_validation(self) -> None:
        with pytest.raises(ValueError, match="Invalid buffer lifetime"):
            Buffer(id="b_bad", lower_time=5, upper_time=3, size=1024)

        with pytest.raises(ValueError, match="Buffer size must be positive"):
            Buffer(id="b_bad_size", lower_time=0, upper_time=5, size=0)

    def test_empty_buffer_solution(self) -> None:
        solver = MiniMalloc()
        solution = solver.solve([])
        assert solution.peak_height == 0
        assert solution.uncompacted_bytes == 0
        assert solution.compaction_ratio == 1.0
        assert solution.verified is True
        assert solution.peak_concurrency_bytes == 0
        assert solution.optimality_gap_pct == 0.0

    def test_non_overlapping_buffers_reuse_offset(self) -> None:
        """Buffers with disjoint lifetimes must reuse offset 0, yielding 2.0x compaction."""
        b1 = Buffer(id="T1", lower_time=0, upper_time=5, size=1024)
        b2 = Buffer(id="T2", lower_time=5, upper_time=10, size=1024)

        solver = MiniMalloc(Configuration(solver=SolverType.CANONICAL))
        solution = solver.solve([b1, b2])

        assert solution.verified is True
        assert solution.offsets["T1"] == 0
        assert solution.offsets["T2"] == 0
        assert solution.peak_height == 1024
        assert solution.uncompacted_bytes == 2048
        assert solution.compaction_ratio == 2.0  # 100% memory reuse
        assert solution.peak_concurrency_bytes == 1024
        assert solution.optimality_gap_pct == 0.0  # 100% optimal

    def test_overlapping_buffers_stacked_spatially(self) -> None:
        """Buffers with concurrent lifetimes must stack without spatial collision."""
        b1 = Buffer(id="A", lower_time=0, upper_time=6, size=1024)
        b2 = Buffer(id="B", lower_time=2, upper_time=8, size=2048)

        solver = MiniMalloc()
        solution = solver.solve([b1, b2])

        assert solution.verified is True
        assert solution.peak_height == 3072
        assert solution.uncompacted_bytes == 3072
        assert solution.compaction_ratio == 1.0
        # Spatial separation
        assert abs(solution.offsets["A"] - solution.offsets["B"]) >= 1024

    def test_asplos_multi_buffer_compaction_gain(self) -> None:
        """Multi-tensor graph scenario achieving high compaction gain and verified 0-overlap."""
        buffers = [
            Buffer(id="Tensor_A", lower_time=0, upper_time=5, size=4096),
            Buffer(id="Tensor_B", lower_time=2, upper_time=8, size=8192),
            Buffer(id="Tensor_C", lower_time=4, upper_time=9, size=4096),
            Buffer(id="Tensor_D", lower_time=6, upper_time=12, size=4096),
            Buffer(id="Tensor_E", lower_time=10, upper_time=15, size=8192),
        ]
        uncompacted = sum(b.size for b in buffers)  # 28,672 bytes

        solver = MiniMalloc(Configuration(solver=SolverType.CANONICAL, dynamic_ordering=True))
        solution = solver.solve(buffers)

        assert solution.verified is True
        assert solution.peak_height < uncompacted
        # Verify compaction gain: compacted height is <= 16,384 bytes (> 1.7x compaction)
        assert solution.peak_height <= 16384
        assert solution.compaction_ratio >= 1.7
        assert solution.solve_time_ms < 50.0  # Fast solving latency

    def test_solver_algorithm_comparison(self) -> None:
        """Compare CANONICAL, FIRST_FIT, and BEST_FIT algorithms."""
        buffers = [
            Buffer(id="B1", lower_time=0, upper_time=4, size=1024),
            Buffer(id="B2", lower_time=1, upper_time=6, size=2048),
            Buffer(id="B3", lower_time=4, upper_time=8, size=1024),
            Buffer(id="B4", lower_time=5, upper_time=10, size=2048),
        ]

        for solver_type in (SolverType.CANONICAL, SolverType.FIRST_FIT, SolverType.BEST_FIT):
            solver = MiniMalloc(Configuration(solver=solver_type))
            solution = solver.solve(buffers)
            assert solution.verified is True
            assert solution.peak_height <= 5120
            assert solution.compaction_ratio >= 1.2

    def test_minimalloc_alignment_avx2(self) -> None:
        """Verify that MiniMalloc strictly enforces 32-byte AVX2 alignment."""
        buffers = [
            Buffer(id="V1", lower_time=0, upper_time=5, size=31),  # Odd size
            Buffer(id="V2", lower_time=2, upper_time=8, size=65),  # Odd size
            Buffer(id="V3", lower_time=4, upper_time=10, size=127),
        ]
        # Align to 32 bytes (AVX2 requirement)
        solver = MiniMalloc(Configuration(alignment=32))
        solution = solver.solve(buffers)

        assert solution.verified is True
        for buf_id, offset in solution.offsets.items():
            assert offset % 32 == 0, f"Offset {offset} for {buf_id} not 32-byte aligned"

    def test_minimalloc_render_ascii_visualization(self) -> None:
        """Verify ASCII rendering produces readable memory stripe map."""
        buffers = [
            Buffer(id="T0", lower_time=0, upper_time=3, size=1024),
            Buffer(id="T1", lower_time=2, upper_time=6, size=2048),
        ]
        solver = MiniMalloc()
        solution = solver.solve(buffers)
        ascii_map = MiniMalloc.render_ascii(buffers, solution, width=40, height=8)

        assert "MiniMalloc 2D Memory Stripe" in ascii_map
        assert "Offset 0B" in ascii_map
        assert "Time:" in ascii_map
        assert "#" in ascii_map
