"""Tests for VectorComputeDispatcher lazy OpenCL dispatcher."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from swarm_sdk.gpu.lazy_dispatcher import VectorComputeDispatcher


class TestLazyLoading:
    """Verify pyopencl is not loaded until batch threshold triggers GPU offload."""

    def test_instantiation_does_not_import_pyopencl(self) -> None:
        """Merely instantiating the dispatcher must NOT import pyopencl into sys.modules."""
        mods_to_remove = [
            m for m in sys.modules if m == "pyopencl" or m.startswith("pyopencl.")
        ]
        saved_mods = {mod: sys.modules.pop(mod) for mod in mods_to_remove}
        try:
            dispatcher = VectorComputeDispatcher(batch_threshold=1000)
            assert "pyopencl" not in sys.modules
            assert dispatcher.is_lazy_loaded is False
        finally:
            sys.modules.update(saved_mods)

    def test_single_vector_dot_does_not_load_pyopencl(self) -> None:
        """Single vector dot product uses CPU and does not load pyopencl."""
        mods_to_remove = [
            m for m in sys.modules if m == "pyopencl" or m.startswith("pyopencl.")
        ]
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

    def test_small_batch_dot_does_not_load_pyopencl(self) -> None:
        """Batch size < threshold uses CPU and does not load pyopencl."""
        mods_to_remove = [
            m for m in sys.modules if m == "pyopencl" or m.startswith("pyopencl.")
        ]
        saved_mods = {mod: sys.modules.pop(mod) for mod in mods_to_remove}
        try:
            dispatcher = VectorComputeDispatcher(batch_threshold=1000)
            mat_a = np.ones((50, 16), dtype=np.float32)
            mat_b = np.ones((50, 16), dtype=np.float32)
            res = dispatcher.compute_batch_dot_product(mat_a, mat_b)
            assert res.shape == (50,)
            assert np.allclose(res, 16.0)
            assert "pyopencl" not in sys.modules
            assert dispatcher.is_lazy_loaded is False
        finally:
            sys.modules.update(saved_mods)


class TestSingleVectorDotProduct:
    """Test compute_dot_product mathematical correctness and CPU optimization."""

    @pytest.fixture
    def dispatcher(self) -> VectorComputeDispatcher:
        return VectorComputeDispatcher()

    def test_basic_dot_product(self, dispatcher: VectorComputeDispatcher) -> None:
        a = np.array([1.0, 3.0, -5.0], dtype=np.float32)
        b = np.array([4.0, -2.0, -1.0], dtype=np.float32)
        # 1*4 + 3*(-2) + (-5)*(-1) = 4 - 6 + 5 = 3.0
        assert dispatcher.compute_dot_product(a, b) == pytest.approx(3.0)

    def test_orthogonal_vectors(self, dispatcher: VectorComputeDispatcher) -> None:
        a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        b = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        assert dispatcher.compute_dot_product(a, b) == pytest.approx(0.0)

    def test_returns_python_float(self, dispatcher: VectorComputeDispatcher) -> None:
        a = np.array([2.5, 3.5], dtype=np.float32)
        b = np.array([2.0, 2.0], dtype=np.float32)
        res = dispatcher.compute_dot_product(a, b)
        assert isinstance(res, float)
        assert res == pytest.approx(12.0)

    def test_dimension_mismatch_raises(self, dispatcher: VectorComputeDispatcher) -> None:
        a = np.array([1.0, 2.0], dtype=np.float32)
        b = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        with pytest.raises(ValueError, match="dimension"):
            dispatcher.compute_dot_product(a, b)


class TestBatchDotProductRoutingAndMath:
    """Test batch dot product with CPU routing (< threshold) and OpenCL (>= threshold)."""

    def test_cpu_batch_dot_pairwise(self) -> None:
        dispatcher = VectorComputeDispatcher(batch_threshold=1000)
        rng = np.random.default_rng(42)
        mat_a = rng.standard_normal((100, 32)).astype(np.float32)
        mat_b = rng.standard_normal((100, 32)).astype(np.float32)

        res = dispatcher.compute_batch_dot_product(mat_a, mat_b)
        expected = np.sum(mat_a * mat_b, axis=1)

        assert res.shape == (100,)
        assert np.allclose(res, expected, atol=1e-5)

    def test_cpu_batch_dot_broadcast_query(self) -> None:
        dispatcher = VectorComputeDispatcher(batch_threshold=1000)
        rng = np.random.default_rng(42)
        mat_a = rng.standard_normal((100, 32)).astype(np.float32)
        vec_b = rng.standard_normal(32).astype(np.float32)

        res = dispatcher.compute_batch_dot_product(mat_a, vec_b)
        expected = mat_a @ vec_b

        assert res.shape == (100,)
        assert np.allclose(res, expected, atol=1e-5)

    def test_threshold_routing_triggers_gpu_when_exceeded(self) -> None:
        """When total vector pairs >= batch_threshold, dispatcher attempts OpenCL."""
        dispatcher = VectorComputeDispatcher(batch_threshold=100)
        rng = np.random.default_rng(42)
        mat_a = rng.standard_normal((150, 64)).astype(np.float32)
        mat_b = rng.standard_normal((150, 64)).astype(np.float32)

        res = dispatcher.compute_batch_dot_product(mat_a, mat_b)
        expected = np.sum(mat_a * mat_b, axis=1)

        assert res.shape == (150,)
        assert np.allclose(res, expected, atol=1e-5)

        info = dispatcher.get_device_info()
        assert info["backend"] in ("opencl", "cpu")
        assert info["lazy_loaded"] is True

    def test_large_batch_computation_correctness(self) -> None:
        dispatcher = VectorComputeDispatcher(batch_threshold=500)
        rng = np.random.default_rng(123)
        mat_a = rng.standard_normal((1200, 128)).astype(np.float32)
        mat_b = rng.standard_normal((1200, 128)).astype(np.float32)

        res = dispatcher.compute_batch_dot_product(mat_a, mat_b)
        expected = np.sum(mat_a * mat_b, axis=1)

        assert res.shape == (1200,)
        assert np.allclose(res, expected, atol=1e-5)

    def test_odd_dimension_batch_correctness(self) -> None:
        """Test non-multiple-of-4 dimension (e.g. 33) to verify scalar kernel fallback."""
        dispatcher = VectorComputeDispatcher(batch_threshold=50)
        rng = np.random.default_rng(456)
        mat_a = rng.standard_normal((100, 33)).astype(np.float32)
        mat_b = rng.standard_normal((100, 33)).astype(np.float32)

        res = dispatcher.compute_batch_dot_product(mat_a, mat_b)
        expected = np.sum(mat_a * mat_b, axis=1)

        assert res.shape == (100,)
        assert np.allclose(res, expected, atol=1e-5)

    def test_dimension_mismatch_raises(self) -> None:
        dispatcher = VectorComputeDispatcher()
        mat_a = np.ones((10, 32), dtype=np.float32)
        mat_b = np.ones((10, 64), dtype=np.float32)
        with pytest.raises(ValueError, match="dimension"):
            dispatcher.compute_batch_dot_product(mat_a, mat_b)


class TestErrorRecoveryAndFallback:
    """Verify robust transparent CPU fallback when OpenCL is unavailable or fails."""

    def test_fallback_when_opencl_not_installed(self) -> None:
        """When pyopencl import fails, transparently executes CPU math."""
        dispatcher = VectorComputeDispatcher(batch_threshold=10)
        with patch.object(dispatcher, "_get_opencl", return_value=None):
            mat_a = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
            mat_b = np.array([[5.0, 6.0], [7.0, 8.0]], dtype=np.float32)

            res = dispatcher.compute_batch_dot_product(mat_a, mat_b)
            expected = np.array([17.0, 53.0], dtype=np.float32)

            assert np.allclose(res, expected)
            info = dispatcher.get_device_info()
            assert info["backend"] == "cpu"
            assert "CPU" in info["device"]

    def test_fallback_when_opencl_kernel_raises_exception(self) -> None:
        """When OpenCL execution raises any exception, catches and executes CPU fallback."""
        dispatcher = VectorComputeDispatcher(batch_threshold=10)
        mat_a = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
        mat_b = np.array([[5.0, 6.0], [7.0, 8.0]], dtype=np.float32)

        with patch.object(
            dispatcher,
            "_run_opencl_batch_dot",
            side_effect=RuntimeError("OpenCL device lost"),
        ):
            res = dispatcher.compute_batch_dot_product(mat_a, mat_b)
            expected = np.array([17.0, 53.0], dtype=np.float32)
            assert np.allclose(res, expected)

    def test_fallback_when_context_creation_fails(self) -> None:
        """When OpenCL context creation fails, catches and executes CPU fallback."""
        dispatcher = VectorComputeDispatcher(batch_threshold=10)
        mock_cl = MagicMock()
        mock_cl.get_platforms.side_effect = RuntimeError("Failed to enumerate OpenCL platforms")

        with patch.object(dispatcher, "_get_opencl", return_value=mock_cl):
            mat_a = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
            mat_b = np.array([[5.0, 6.0], [7.0, 8.0]], dtype=np.float32)

            res = dispatcher.compute_batch_dot_product(mat_a, mat_b)
            expected = np.array([17.0, 53.0], dtype=np.float32)
            assert np.allclose(res, expected)


class TestDeviceInfo:
    """Test get_device_info returns active device, backend, and lazy loaded status."""

    def test_device_info_structure(self) -> None:
        dispatcher = VectorComputeDispatcher()
        info = dispatcher.get_device_info()
        assert "device" in info
        assert "backend" in info
        assert "lazy_loaded" in info
        assert isinstance(info["lazy_loaded"], bool)
        assert info["backend"] in ("opencl", "cpu")

    def test_device_info_cpu_fallback(self) -> None:
        dispatcher = VectorComputeDispatcher()
        with patch.object(dispatcher, "_get_opencl", return_value=None):
            info = dispatcher.get_device_info()
            assert info["backend"] == "cpu"
            assert info["device"] == "CPU (Host Native AVX2)"
            assert info["lazy_loaded"] is False


class TestReExport:
    """Verify VectorComputeDispatcher is cleanly re-exported in swarm_sdk.gpu."""

    def test_reexported_in_package(self) -> None:
        import swarm_sdk.gpu as gpu_pkg

        assert hasattr(gpu_pkg, "VectorComputeDispatcher")
        assert "VectorComputeDispatcher" in gpu_pkg.__all__
        from swarm_sdk.gpu import VectorComputeDispatcher as ExportedDispatcher

        assert ExportedDispatcher is VectorComputeDispatcher
