"""Dynamic memory allocator management, telemetry, and mimalloc integration."""

from __future__ import annotations

import contextlib
import ctypes
import gc
import os
import resource
import sys
import time
from collections.abc import Generator
from dataclasses import dataclass
from typing import Any

from swarm_sdk.execution import gil_enabled


class _ProcTaskInfo(ctypes.Structure):
    """macOS ``struct proc_taskinfo`` (``PROC_PIDTASKINFO``)."""

    _fields_ = [
        ("virtual_size", ctypes.c_uint64),
        ("resident_size", ctypes.c_uint64),
        ("total_user", ctypes.c_uint64),
        ("total_system", ctypes.c_uint64),
        ("threads_user", ctypes.c_uint64),
        ("threads_system", ctypes.c_uint64),
        *(
            (name, ctypes.c_int32)
            for name in (
                "policy",
                "faults",
                "pageins",
                "cow_faults",
                "messages_sent",
                "messages_received",
                "syscalls_mach",
                "syscalls_unix",
                "csw",
                "threadnum",
                "numrunning",
                "priority",
            )
        ),
    ]


def _current_rss_bytes() -> int | None:
    """Live resident set size of this process, or ``None`` if the platform gives none."""
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/self/statm", encoding="ascii") as handle:
                return int(handle.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
        if sys.platform == "darwin":
            libproc = ctypes.CDLL("/usr/lib/libproc.dylib")
            info = _ProcTaskInfo()
            size = ctypes.sizeof(info)
            proc_pidtaskinfo = 4
            got = libproc.proc_pidinfo(os.getpid(), proc_pidtaskinfo, 0, ctypes.byref(info), size)
            return int(info.resident_size) if got == size else None
    except (OSError, ValueError, IndexError, AttributeError):
        return None
    return None


@dataclass(frozen=True, slots=True)
class MemoryStats:
    """Current memory profile of the Swarm process."""

    allocator: str
    rss_mb: float
    rss_gb: float
    free_threaded: bool
    gil_enabled: bool
    platform: str


@dataclass(slots=True)
class GuardReport:
    """Telemetry report recorded during a guarded execution block."""

    initial_rss_mb: float
    final_rss_mb: float
    delta_rss_mb: float
    ceiling_gb: float
    duration_ms: float
    breached: bool = False


class AllocatorManager:
    """Detects, inspects, and benchmarks memory allocators for Swarm workloads."""

    def __init__(self) -> None:
        """Initialize allocator tracking for the current process."""
        self._allocator_name = self._detect_allocator()

    @staticmethod
    def _detect_allocator() -> str:
        """Determines the active memory allocator in the running Python process."""
        pythonmalloc = os.environ.get("PYTHONMALLOC", "").lower()
        if pythonmalloc == "mimalloc":
            return "mimalloc"

        # Check free-threaded Python 3.14+ (mimalloc is the default engine)
        if not gil_enabled():
            return "mimalloc (free-threaded default)"

        # Check DYLD_INSERT_LIBRARIES or LD_PRELOAD
        preload = os.environ.get("DYLD_INSERT_LIBRARIES", "") or os.environ.get("LD_PRELOAD", "")
        if "mimalloc" in preload.lower():
            return "mimalloc (preloaded)"
        if "jemalloc" in preload.lower():
            return "jemalloc (preloaded)"

        if sys.platform == "darwin":
            return "Darwin libsystem_malloc"
        return "glibc ptmalloc"

    @property
    def allocator_name(self) -> str:
        """Name of the detected active heap allocator."""
        return self._allocator_name

    @property
    def is_mimalloc(self) -> bool:
        """True if Microsoft mimalloc is actively managing Python heap allocations."""
        return "mimalloc" in self._allocator_name

    @staticmethod
    def get_rss_bytes() -> int:
        """Returns the current process resident set size (RSS) in bytes.

        Reads live RSS (``/proc`` on Linux, ``proc_pidinfo`` on macOS); falls back to the
        peak (``ru_maxrss``) only when the live value is unavailable.
        """
        current = _current_rss_bytes()
        if current is not None:
            return current
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":
            # macOS returns ru_maxrss in bytes
            return int(usage)
        # Linux returns ru_maxrss in kilobytes
        return int(usage * 1024)

    @classmethod
    def get_current_rss_gb(cls) -> float:
        """Returns current process RSS in gigabytes."""
        return cls.get_rss_bytes() / (1024**3)

    def get_memory_stats(self) -> MemoryStats:
        """Collects structured memory statistics for observability and logging."""
        rss_bytes = self.get_rss_bytes()
        rss_mb = rss_bytes / (1024 * 1024)
        rss_gb = rss_bytes / (1024**3)

        gil_on = gil_enabled()
        free_threaded = not gil_on

        return MemoryStats(
            allocator=self._allocator_name,
            rss_mb=round(rss_mb, 2),
            rss_gb=round(rss_gb, 4),
            free_threaded=free_threaded,
            gil_enabled=gil_on,
            platform=sys.platform,
        )

    @staticmethod
    def trim_memory() -> dict[str, Any]:
        """Triggers full garbage collection and attempts to release unused arena pages to OS."""
        initial_rss = AllocatorManager.get_rss_bytes()
        unreachable = gc.collect()

        mi_reclaimed = False
        # Attempt to call mi_collect(True) if mimalloc is loaded
        for lib_name in ("libmimalloc.dylib", "libmimalloc.so.2", "libmimalloc.so"):
            try:
                mi_lib = ctypes.CDLL(lib_name)
                if hasattr(mi_lib, "mi_collect"):
                    mi_lib.mi_collect(ctypes.c_bool(True))
                    mi_reclaimed = True
                    break
            except (OSError, AttributeError):
                continue

        final_rss = AllocatorManager.get_rss_bytes()
        reclaimed_bytes = max(0, initial_rss - final_rss)

        return {
            "unreachable_objects_collected": unreachable,
            "mimalloc_arena_purged": mi_reclaimed,
            "reclaimed_mb": round(reclaimed_bytes / (1024 * 1024), 3),
            "current_rss_mb": round(final_rss / (1024 * 1024), 2),
        }

    @staticmethod
    @contextlib.contextmanager
    def guard_memory(ceiling_gb: float = 13.6) -> Generator[GuardReport]:
        """Context manager that monitors RSS and enforces the host memory ceiling (< 13.6 GB).

        Args:
            ceiling_gb: Maximum allowable memory ceiling in gigabytes (default 13.6 GB
                for a 16 GB host).

        Yields:
            GuardReport object with execution telemetry.

        Raises:
            MemoryError: If current RSS exceeds the specified ceiling_gb.
        """
        initial_bytes = AllocatorManager.get_rss_bytes()
        initial_mb = initial_bytes / (1024 * 1024)
        initial_gb = initial_bytes / (1024**3)

        if initial_gb >= ceiling_gb:
            raise MemoryError(
                f"Memory ceiling exceeded before block execution: "
                f"{initial_gb:.2f} GB >= {ceiling_gb:.2f} GB"
            )

        report = GuardReport(
            initial_rss_mb=round(initial_mb, 2),
            final_rss_mb=round(initial_mb, 2),
            delta_rss_mb=0.0,
            ceiling_gb=ceiling_gb,
            duration_ms=0.0,
            breached=False,
        )

        start_time = time.perf_counter()
        try:
            yield report
        finally:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            final_bytes = AllocatorManager.get_rss_bytes()
            final_mb = final_bytes / (1024 * 1024)
            final_gb = final_bytes / (1024**3)

            report.final_rss_mb = round(final_mb, 2)
            report.delta_rss_mb = round(final_mb - initial_mb, 2)
            report.duration_ms = round(elapsed_ms, 3)

            if final_gb >= ceiling_gb:
                report.breached = True
                raise MemoryError(
                    f"Lifeguard memory ceiling breached during execution: "
                    f"{final_gb:.2f} GB >= {ceiling_gb:.2f} GB"
                )

    @staticmethod
    def benchmark_allocation(num_ops: int = 200_000, chunk_size: int = 128) -> dict[str, float]:
        """Runs a synthetic allocation benchmark to quantify allocator throughput.

        Args:
            num_ops: Number of allocate-and-free operations.
            chunk_size: Byte size of allocated bytearray buffers.

        Returns:
            Dictionary reporting total time (ms), ops/sec, and latency (ns/op).
        """
        start = time.perf_counter()
        # Allocate, touch, and discard buffers in a tight loop
        for _ in range(num_ops):
            b = bytearray(chunk_size)
            b[0] = 0xAA
            del b
        elapsed = time.perf_counter() - start

        ops_per_sec = num_ops / elapsed if elapsed > 0 else float("inf")
        ns_per_op = (elapsed / num_ops) * 1e9 if num_ops > 0 else 0.0

        return {
            "total_ms": round(elapsed * 1000.0, 3),
            "ops_per_sec": round(ops_per_sec, 1),
            "ns_per_op": round(ns_per_op, 2),
        }


__all__ = ["AllocatorManager", "GuardReport", "MemoryStats"]
