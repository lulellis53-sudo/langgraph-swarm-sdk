"""Tests for VectorComputeDispatcher lazy OpenCL dispatcher."""

from __future__ import annotations

import sys

import numpy as np
import pytest

from swarm_sdk.gpu.lazy_dispatcher import VectorComputeDispatcher


class TestLazyLoading:
    """Verify pyopencl is not loaded until batch threshold triggers GPU offload."""

    def test_instantiation_does_not_import_pyopencl(self) -> None:
        mods_to_remove = [m for m in sys.modules if m == "pyopencl" or m.startswith("pyopencl.")]
        saved_mods = {mod: sys.modules.pop(mod) for mod in mods_to_remove}
        try:
            dispatcher = VectorComputeDispatcher(batch_threshold=1000)
            assert "pyopencl" not in sys.modules
            assert dispatcher.is_lazy_loaded is False
        finally:
            sys.modules.update(saved_mods)

    def test_single_vector_dot_does_not_load_pyopencl(self) -> None:
        mods_to_remove = [m for m in sys.modules if m == "pyopencl" or m.startswith("pyopencl.")]
        saved_mods = {mod: sys.modules.pop(mod) for mod in mods_to_remove}
        try:
            dispatcher = VectorComputeDispatcher(batch_threshold=1000)
            vec_a = np.array([1.0, 2.0, 3.0], dtype=np.float32)
            vec_b = np.array([4.0, 5.0, 6.0], dtype=np.float32)
            res = dispatcher.compute_dot_product(vec_a, vec_b)
            assert res == pytest.approx(32.0)
            assert "pyopencl" not in sys.modules
            assert dispatcher.is_lazy_loaded is False
        finally:
            sys.modules.update(saved_mods)


def test_opencl_package_imports() -> None:
    import swarm_sdk.opencl as opencl

    assert opencl.opencl_available is not None
    assert callable(opencl.batch_dot)
