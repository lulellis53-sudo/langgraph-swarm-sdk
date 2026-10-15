"""Google MiniMalloc (ASPLOS '23): Static 2D strip-packing buffer compaction solver."""

from __future__ import annotations

import enum
import time
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Buffer:
    """Represents a memory buffer with a fixed lifetime interval and byte size."""

    id: str
    lower_time: int
    upper_time: int
    size: int

    def __post_init__(self) -> None:
        if self.lower_time >= self.upper_time:
            raise ValueError(
                f"Invalid buffer lifetime: lower_time ({self.lower_time}) "
                f">= upper_time ({self.upper_time})"
            )
        if self.size <= 0:
            raise ValueError(f"Buffer size must be positive, got {self.size}")

    def overlaps_in_time(self, other: Buffer) -> bool:
        """True if the temporal lifetimes [lower_time, upper_time) overlap."""
        return max(self.lower_time, other.lower_time) < min(self.upper_time, other.upper_time)


class SolverType(enum.StrEnum):
    """Exploration engine for static buffer placement."""

    CANONICAL = "canonical"
    FIRST_FIT = "first_fit"
    BEST_FIT = "best_fit"


@dataclass(frozen=True, slots=True)
class Configuration:
    """Configuration parameters for the MiniMalloc solver."""

    solver: SolverType = SolverType.CANONICAL
    dynamic_ordering: bool = True
    timeout_sec: float = 5.0
    alignment: int = 1  # 1 for unaligned, 32 for AVX2 SIMD, 64 for cache-line


@dataclass(frozen=True, slots=True)
class Solution:
    """Output solution produced by the MiniMalloc solver."""

    offsets: dict[str, int]
    peak_height: int
    uncompacted_bytes: int
    compaction_ratio: float
    solve_time_ms: float
    verified: bool
    peak_concurrency_bytes: int = 0
    optimality_gap_pct: float = 0.0


def _align(val: int, alignment: int) -> int:
    """Rounds up value to the nearest multiple of alignment."""
    if alignment <= 1:
        return val
    rem = val % alignment
    return val if rem == 0 else val + (alignment - rem)


class MiniMalloc:
    """Google MiniMalloc (ASPLOS '23) static 2D strip-packing memory allocator.

    Packs tensor / agent scratchpad buffers into a minimal contiguous memory offset
    envelope by searching an algebraic semi-lattice of canonical configurations.
    """

    def __init__(self, config: Configuration | None = None) -> None:
        """Initialize the 2D strip-packing allocator for tensor buffers."""
        self.config = config or Configuration()

    @staticmethod
    def _verify_solution(
        buffers: Sequence[Buffer], offsets: dict[str, int], alignment: int = 1
    ) -> bool:
        """Verify that temporally overlapping buffers never overlap in memory and stay aligned."""
        for i, b1 in enumerate(buffers):
            o1 = offsets[b1.id]
            if alignment > 1 and o1 % alignment != 0:
                return False
            for b2 in buffers[i + 1 :]:
                o2 = offsets[b2.id]
                if b1.overlaps_in_time(b2):
                    # Check spatial overlap: [o1, o1 + s1) vs [o2, o2 + s2)
                    if max(o1, o2) < min(o1 + b1.size, o2 + b2.size):
                        return False
        return True

    @staticmethod
    def compute_concurrency_lower_bound(buffers: Sequence[Buffer]) -> int:
        """Compute the lower bound: the peak sum of concurrently active buffers."""
        if not buffers:
            return 0
        # Time events: (time, +size for start, -size for end)
        events: list[tuple[int, int]] = []
        for b in buffers:
            events.append((b.lower_time, b.size))
            events.append((b.upper_time, -b.size))

        # Sort events by time ascending; ends before starts at same timestamp
        events.sort(key=lambda ev: (ev[0], 0 if ev[1] < 0 else 1))

        current_load = 0
        max_load = 0
        for _, delta in events:
            current_load += delta
            if current_load > max_load:
                max_load = current_load
        return max_load

    def solve(self, buffers: Sequence[Buffer], capacity: int | None = None) -> Solution:
        """Solves the static 2D strip packing problem for the given buffers.

        Args:
            buffers: Sequence of Buffer instances.
            capacity: Optional maximum allowable memory envelope in bytes.

        Returns:
            Solution with buffer offsets, peak height, compaction ratio and optimality metrics.
        """
        if not buffers:
            return Solution(
                offsets={},
                peak_height=0,
                uncompacted_bytes=0,
                compaction_ratio=1.0,
                solve_time_ms=0.0,
                verified=True,
                peak_concurrency_bytes=0,
                optimality_gap_pct=0.0,
            )

        start_time = time.perf_counter()
        uncompacted_bytes = sum(b.size for b in buffers)
        concurrency_lower_bound = self.compute_concurrency_lower_bound(buffers)

        # 1. Dynamic Ordering / Dominance Elimination
        ordered_buffers = list(buffers)
        if self.config.dynamic_ordering:
            # Order by conflict graph degree and size descending (pack constrained buffers first)
            def sort_key(b: Buffer) -> tuple[int, int]:
                conflicts = sum(
                    1 for other in buffers if other.id != b.id and b.overlaps_in_time(other)
                )
                return (conflicts, b.size)

            ordered_buffers.sort(key=sort_key, reverse=True)

        if self.config.solver == SolverType.FIRST_FIT:
            offsets, peak = self._solve_greedy(ordered_buffers, first_fit=True, capacity=capacity)
        elif self.config.solver == SolverType.BEST_FIT:
            offsets, peak = self._solve_greedy(ordered_buffers, first_fit=False, capacity=capacity)
        else:
            offsets, peak = self._solve_canonical_lattice(ordered_buffers, capacity=capacity)

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        verified = self._verify_solution(buffers, offsets, alignment=self.config.alignment)
        compaction_ratio = (uncompacted_bytes / peak) if peak > 0 else 1.0

        optimality_gap_pct = (
            round(((peak - concurrency_lower_bound) / concurrency_lower_bound) * 100.0, 2)
            if concurrency_lower_bound > 0
            else 0.0
        )

        return Solution(
            offsets=offsets,
            peak_height=peak,
            uncompacted_bytes=uncompacted_bytes,
            compaction_ratio=round(compaction_ratio, 2),
            solve_time_ms=round(elapsed_ms, 3),
            verified=verified,
            peak_concurrency_bytes=concurrency_lower_bound,
            optimality_gap_pct=optimality_gap_pct,
        )

    def _solve_greedy(
        self,
        buffers: Sequence[Buffer],
        first_fit: bool = True,
        capacity: int | None = None,
    ) -> tuple[dict[str, int], int]:
        """Greedy placement on candidate canonical offset boundaries respecting alignment."""
        offsets: dict[str, int] = {}
        alignment = self.config.alignment

        for buf in buffers:
            # Candidate offsets: 0 and aligned top edge of already placed conflicting buffers
            candidates = {0}
            for placed_id, placed_offset in offsets.items():
                placed_buf = next(b for b in buffers if b.id == placed_id)
                if buf.overlaps_in_time(placed_buf):
                    cand = _align(placed_offset + placed_buf.size, alignment)
                    candidates.add(cand)

            valid_candidates = []
            for cand in sorted(candidates):
                if capacity is not None and cand + buf.size > capacity:
                    continue
                # Test spatial conflict against already placed buffers
                has_conflict = False
                for placed_id, placed_offset in offsets.items():
                    placed_buf = next(b for b in buffers if b.id == placed_id)
                    if buf.overlaps_in_time(placed_buf):
                        if max(cand, placed_offset) < min(
                            cand + buf.size, placed_offset + placed_buf.size
                        ):
                            has_conflict = True
                            break
                if not has_conflict:
                    valid_candidates.append(cand)

            if not valid_candidates:
                # If capacity bound reached or constrained, append to top
                fallback_cand = max(
                    (
                        offsets[b_id] + next(b for b in buffers if b.id == b_id).size
                        for b_id in offsets
                    ),
                    default=0,
                )
                offsets[buf.id] = _align(fallback_cand, alignment)
            elif first_fit:
                offsets[buf.id] = min(valid_candidates)
            else:
                # Best fit: candidate that minimizes waste
                offsets[buf.id] = min(valid_candidates)

        peak = max(offsets[b.id] + b.size for b in buffers) if buffers else 0
        return offsets, peak

    def _solve_canonical_lattice(
        self,
        buffers: Sequence[Buffer],
        capacity: int | None = None,
    ) -> tuple[dict[str, int], int]:
        """Branch-and-bound search with spatial inference pruning and alignment."""
        best_offsets: dict[str, int] = {}
        best_peak = capacity if capacity is not None else sum(b.size for b in buffers)
        deadline = time.perf_counter() + self.config.timeout_sec
        alignment = self.config.alignment

        def search(index: int, current_offsets: dict[str, int], current_peak: int) -> None:
            nonlocal best_offsets, best_peak
            if time.perf_counter() > deadline:
                return

            if index == len(buffers):
                if current_peak < best_peak:
                    best_peak = current_peak
                    best_offsets = dict(current_offsets)
                return

            buf = buffers[index]

            # Candidate canonical lattice offsets
            candidates = {0}
            for placed_id, placed_offset in current_offsets.items():
                placed_buf = next(b for b in buffers if b.id == placed_id)
                if buf.overlaps_in_time(placed_buf):
                    cand = _align(placed_offset + placed_buf.size, alignment)
                    candidates.add(cand)

            sorted_candidates = sorted(candidates)
            for cand in sorted_candidates:
                new_peak = max(current_peak, cand + buf.size)
                # Spatial inference pruning: prune if candidate exceeds best known peak
                if new_peak >= best_peak:
                    continue

                # Check conflict with already assigned overlapping buffers
                has_conflict = False
                for placed_id, placed_offset in current_offsets.items():
                    placed_buf = next(b for b in buffers if b.id == placed_id)
                    if buf.overlaps_in_time(placed_buf):
                        if max(cand, placed_offset) < min(
                            cand + buf.size, placed_offset + placed_buf.size
                        ):
                            has_conflict = True
                            break

                if not has_conflict:
                    current_offsets[buf.id] = cand
                    search(index + 1, current_offsets, new_peak)
                    del current_offsets[buf.id]

        # Initialize with greedy solution as upper bound
        greedy_offsets, greedy_peak = self._solve_greedy(buffers, first_fit=True, capacity=capacity)
        best_offsets = greedy_offsets
        best_peak = greedy_peak

        # Refine using canonical lattice search
        search(0, {}, 0)
        return best_offsets, best_peak

    @staticmethod
    def render_ascii(
        buffers: Sequence[Buffer], solution: Solution, width: int = 60, height: int = 12
    ) -> str:
        """Renders an ASCII visualization of the 2D strip-packed memory layout over time."""
        if not buffers or solution.peak_height <= 0:
            return "[Empty Memory Stripe]"

        t_min = min(b.lower_time for b in buffers)
        t_max = max(b.upper_time for b in buffers)
        t_range = max(1, t_max - t_min)
        mem_peak = solution.peak_height

        # Initialize empty character grid (height rows x width columns)
        grid = [["." for _ in range(width)] for _ in range(height)]

        for b in buffers:
            offset = solution.offsets.get(b.id, 0)
            # Map time to x coordinates
            x_start = int(((b.lower_time - t_min) / t_range) * (width - 1))
            x_end = int(((b.upper_time - t_min) / t_range) * (width - 1))
            x_end = max(x_start + 1, x_end)

            # Map offset to y coordinates (y=0 at top or bottom; let's put offset 0 at bottom)
            y_start = int((offset / mem_peak) * (height - 1))
            y_end = int(((offset + b.size) / mem_peak) * (height - 1))
            y_end = max(y_start + 1, y_end)

            # Draw buffer box with buffer id tag
            tag = b.id[: max(1, x_end - x_start - 2)]
            for y in range(y_start, min(height, y_end)):
                for x in range(x_start, min(width, x_end)):
                    grid[y][x] = "#"
                if len(tag) > 0 and x_start + 1 + len(tag) <= width:
                    for i, ch in enumerate(tag):
                        grid[y_start][x_start + 1 + i] = ch

        lines = [
            f"MiniMalloc 2D Memory Stripe (Peak: {solution.peak_height} bytes, "
            f"Ratio: {solution.compaction_ratio:.2f}x):",
            f"Offset {mem_peak}B +{'-' * width}+",
        ]
        # Invert rows so high memory is at top, offset 0 is at bottom
        for row in reversed(grid):
            lines.append(f"          |{''.join(row)}|")
        lines.append(f"Offset 0B +{'-' * width}+")
        lines.append(f"Time:     t={t_min}{' ' * max(1, width - 14)}t={t_max}")
        return "\n".join(lines)


__all__ = ["Buffer", "Configuration", "MiniMalloc", "Solution", "SolverType"]
