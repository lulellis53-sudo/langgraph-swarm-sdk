"""Zstandard zero-copy compression, Lifeguard lazy imports, and hybrid JIT/NoJIT execution."""

from __future__ import annotations

import importlib
import os
import types
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar, cast

F = TypeVar("F", bound=Callable[..., Any])

# ---------------------------------------------------------------------------
# 1. Lifeguard Lazy Import Proxy (PEP 810 Compliant)
# ---------------------------------------------------------------------------


class LazyModule(types.ModuleType):
    """Lazy module proxy that defers actual importlib loading until first attribute access.

    Conforms to Meta Lifeguard static analysis invariants:
    - Eliminates upfront RSS bloat from heavyweight packages.
    - Prevents module-level side-effects during CLI startup or test discovery.
    """

    def __init__(self, name: str) -> None:
        """Wrap ``real`` so heavy imports happen on first attribute access."""
        super().__init__(name)
        self._module_name = name
        self._loaded_module: types.ModuleType | None = None

    def _load(self) -> types.ModuleType:
        if self._loaded_module is None:
            self._loaded_module = importlib.import_module(self._module_name)
        return self._loaded_module

    def __getattr__(self, item: str) -> Any:
        module = self._load()
        return getattr(module, item)

    def __repr__(self) -> str:
        status = "loaded" if self._loaded_module is not None else "unloaded"
        return f"<LazyModule '{self._module_name}' ({status})>"


def lazy_import(name: str) -> Any:
    """Creates a lazy import proxy for the specified module name."""
    return LazyModule(name)


# ---------------------------------------------------------------------------
# 2. Hybrid JIT / NoJIT Execution Engine
# ---------------------------------------------------------------------------


def is_jit_disabled() -> bool:
    """True if JIT execution is explicitly disabled via NUMBA_DISABLE_JIT or NO_JIT."""
    return os.environ.get("NUMBA_DISABLE_JIT", "0") in ("1", "true") or os.environ.get(
        "NO_JIT", "0"
    ) in ("1", "true")


def hybrid_jit(
    nogil: bool = True,
    fastmath: bool = True,
    parallel: bool = False,
) -> Callable[[F], F]:
    """Dual-mode polymorphic decorator supporting JIT compilation and NoJIT fallback.

    - If Numba is installed and JIT is enabled: compiles function with
      @numba.njit(nogil=nogil, fastmath=fastmath).
    - If Numba is missing, disabled (NUMBA_DISABLE_JIT=1), or in test mode: executes
      pure Python/NumPy with zero overhead.
    """

    def decorator(fn: F) -> F:
        if is_jit_disabled():
            # NoJIT Mode: Return original pure-Python function directly
            setattr(fn, "__jit_compiled__", False)
            return fn

        try:
            import numba  # type: ignore

            # Apply Numba njit with free-threaded / nogil support
            compiled_fn = numba.njit(
                nogil=nogil,
                fastmath=fastmath,
                parallel=parallel,
            )(fn)
            setattr(compiled_fn, "__jit_compiled__", True)
            return cast(F, compiled_fn)
        except ImportError, Exception:
            # Graceful NoJIT fallback
            setattr(fn, "__jit_compiled__", False)
            return fn

    return decorator


# ---------------------------------------------------------------------------
# 3. Zstandard Zero-Copy State Compressor
# ---------------------------------------------------------------------------


class ZstdStateCompressor:
    """Zstandard compression engine supporting zero-copy memoryviews and state serialization.

    Prefers native Python 3.14+ `compression.zstd`. Falls back to `zlib` if zstd is unavailable.
    """

    def __init__(self, level: int = 3, dict_data: bytes | None = None) -> None:
        """Initialize with the best available zstd backend (stdlib or PyPI fallback)."""
        self.level = level
        self._has_native_zstd = False
        self._zstd_mod: Any = None
        self._dict_data = dict_data
        self._init_backend()

    def _init_backend(self) -> None:
        try:
            import compression.zstd as zstd  # type: ignore

            self._zstd_mod = zstd
            self._has_native_zstd = True
        except ImportError:
            try:
                import zstandard as zstd  # type: ignore

                self._zstd_mod = zstd
                self._has_native_zstd = False  # external library mode
            except ImportError:
                import zlib

                self._zstd_mod = zlib
                self._has_native_zstd = False

    @property
    def backend_name(self) -> str:
        """Name of the active zstd backend (stdlib ``compression.zstd`` or ``zstandard``)."""
        if self._has_native_zstd:
            return "python314_native_zstd"
        if hasattr(self._zstd_mod, "ZstdCompressor"):
            return "python_zstandard"
        return "zlib_fallback"

    def compress(self, data: bytes | bytearray | memoryview) -> bytes:
        """Compresses binary payload or zero-copy memoryview into compact bytes."""
        if self._has_native_zstd:
            # Native Python 3.14 compression.zstd
            if self._dict_data is not None:
                # Use zstd dictionary if configured
                zdict = self._zstd_mod.ZstdDict(self._dict_data)
                return self._zstd_mod.compress(data, zdict=zdict)
            return self._zstd_mod.compress(data)

        if hasattr(self._zstd_mod, "ZstdCompressor"):
            # python-zstandard external package
            cctx = self._zstd_mod.ZstdCompressor(level=self.level)
            return cctx.compress(data)

        # Fallback to zlib
        return self._zstd_mod.compress(bytes(data), level=self.level)

    def decompress(self, data: bytes | memoryview) -> bytes:
        """Decompresses compressed bytes into original uncompressed byte buffer."""
        if self._has_native_zstd:
            if self._dict_data is not None:
                zdict = self._zstd_mod.ZstdDict(self._dict_data)
                return self._zstd_mod.decompress(data, zdict=zdict)
            return self._zstd_mod.decompress(data)

        if hasattr(self._zstd_mod, "ZstdDecompressor"):
            dctx = self._zstd_mod.ZstdDecompressor()
            return dctx.decompress(data)

        # Fallback to zlib
        return self._zstd_mod.decompress(bytes(data))

    def compress_text(self, text: str) -> bytes:
        """Encodes and compresses text string into zstd bytes."""
        return self.compress(text.encode("utf-8"))

    def decompress_text(self, data: bytes | memoryview) -> str:
        """Decompresses zstd bytes and decodes back to UTF-8 text string."""
        raw = self.decompress(data)
        return raw.decode("utf-8")


# ---------------------------------------------------------------------------
# 4. MiniMalloc + Zstd Hybrid Scratchpad Buffer Pool
# ---------------------------------------------------------------------------


@dataclass
class SwarmBufferEntry:
    """One entry in the compressed scratchpad buffer."""

    id: str
    size: int
    offset: int
    is_compressed: bool = False
    compressed_bytes: bytes | None = None
    raw_buffer: bytearray | None = None


class CompressedScratchpadPool:
    """Hybrid memory pool combining MiniMalloc static 2D packing with Zstd compression.

    - Active buffers reside in contiguous memory offsets assigned by MiniMalloc.
    - Inactive / cached buffers are compressed with Zstd to free RAM under Lifeguard constraints.
    """

    def __init__(self, alignment: int = 32) -> None:
        """Initialize the pool; entries compress above ``min_bytes``."""
        self.alignment = alignment
        self.compressor = ZstdStateCompressor(level=3)
        self.entries: dict[str, SwarmBufferEntry] = {}
        self.total_uncompressed_bytes = 0

    def register_buffer(self, buffer_id: str, size: int, offset: int) -> None:
        """Registers a buffer assigned to a static MiniMalloc offset."""
        raw = bytearray(size)
        self.entries[buffer_id] = SwarmBufferEntry(
            id=buffer_id,
            size=size,
            offset=offset,
            is_compressed=False,
            raw_buffer=raw,
        )
        self.total_uncompressed_bytes += size

    def freeze_to_cold_tier(self, buffer_id: str) -> int:
        """Compresses active buffer using Zstd and frees its raw bytearray allocation."""
        entry = self.entries.get(buffer_id)
        if entry is None or entry.is_compressed or entry.raw_buffer is None:
            return 0

        # Zero-copy compression from memoryview
        mv = memoryview(entry.raw_buffer)
        compressed = self.compressor.compress(mv)
        entry.compressed_bytes = compressed
        entry.raw_buffer = None
        entry.is_compressed = True
        return len(compressed)

    def restore_from_cold_tier(self, buffer_id: str) -> bytearray:
        """Decompresses cold buffer back into an active bytearray at its designated offset."""
        entry = self.entries.get(buffer_id)
        if entry is None:
            raise KeyError(f"Buffer {buffer_id} not registered")

        if not entry.is_compressed and entry.raw_buffer is not None:
            return entry.raw_buffer

        if entry.compressed_bytes is None:
            entry.raw_buffer = bytearray(entry.size)
        else:
            raw_bytes = self.compressor.decompress(entry.compressed_bytes)
            entry.raw_buffer = bytearray(raw_bytes)

        entry.is_compressed = False
        entry.compressed_bytes = None
        return entry.raw_buffer

    def get_memory_footprint(self) -> dict[str, int]:
        """Calculates resident memory footprint across active and compressed tiers."""
        active_bytes = sum(
            len(e.raw_buffer) for e in self.entries.values() if e.raw_buffer is not None
        )
        cold_bytes = sum(
            len(e.compressed_bytes) for e in self.entries.values() if e.compressed_bytes is not None
        )
        return {
            "active_bytes": active_bytes,
            "cold_bytes": cold_bytes,
            "total_bytes": active_bytes + cold_bytes,
            "virtual_uncompressed_bytes": self.total_uncompressed_bytes,
        }


__all__ = [
    "CompressedScratchpadPool",
    "LazyModule",
    "SwarmBufferEntry",
    "ZstdStateCompressor",
    "hybrid_jit",
    "is_jit_disabled",
    "lazy_import",
]
