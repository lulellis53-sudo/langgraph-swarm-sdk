"""Tests for the GPU math dispatcher and its NumPy fallback."""

from __future__ import annotations

import numpy as np
import pytest

from swarm_sdk.gpu import (
    batch_cosine,
    batch_dot,
    l2_norm,
    normalize,
    opencl_available,
    reset_opencl,
    set_enabled,
    topk_ip,
)


def _random_matrix(rows: int, cols: int) -> np.ndarray:
    rng = np.random.default_rng(42)
    return rng.standard_normal((rows, cols)).astype(np.float32)


@pytest.fixture(autouse=True)
def _disable_opencl_for_cpu_fallback(monkeypatch):
    """Most tests run against the NumPy fallback so they pass without pyopencl."""
    set_enabled(False)
    yield
    set_enabled(True)
    reset_opencl()


def test_l2_norm_matches_numpy():
    matrix = _random_matrix(8, 16)
    expected = np.linalg.norm(matrix, axis=1).astype(np.float32)
    np.testing.assert_allclose(l2_norm(matrix), expected, rtol=1e-5)


def test_normalize_makes_unit_vectors():
    matrix = _random_matrix(8, 16)
    normalized = normalize(matrix)
    norms = np.linalg.norm(normalized, axis=1)
    np.testing.assert_allclose(norms, 1.0, rtol=1e-5)


def test_normalize_preserves_zero_vectors():
    matrix = np.zeros((4, 8), dtype=np.float32)
    normalized = normalize(matrix)
    np.testing.assert_array_equal(normalized, matrix)


def test_batch_dot_matches_numpy():
    matrix = _random_matrix(8, 16)
    query = _random_matrix(1, 16).reshape(-1)
    expected = matrix @ query
    np.testing.assert_allclose(batch_dot(query, matrix), expected, rtol=1e-5)


def test_batch_cosine_matches_numpy():
    matrix = _random_matrix(8, 16)
    query = _random_matrix(1, 16).reshape(-1)
    expected = batch_cosine(query, matrix)
    q_norm = np.linalg.norm(query)
    m_norm = np.linalg.norm(matrix, axis=1)
    q_norm = q_norm if q_norm != 0 else 1.0
    m_norm = np.where(m_norm == 0, 1.0, m_norm)
    manual = (matrix @ query) / (m_norm * q_norm)
    np.testing.assert_allclose(expected, manual, rtol=1e-5)


def test_topk_ip_returns_best_scores():
    matrix = _random_matrix(8, 16)
    query = _random_matrix(1, 16).reshape(-1)
    idx, scores = topk_ip(query, matrix, k=3)
    assert idx.shape == (3,)
    assert scores.shape == (3,)
    assert np.all(np.diff(scores) <= 0), "scores should be descending"
    expected_scores = matrix @ query
    for i, s in zip(idx, scores, strict=True):
        assert pytest.approx(s, rel=1e-5) == expected_scores[int(i)]


def test_topk_ip_clamps_to_available_rows():
    matrix = _random_matrix(2, 8)
    query = _random_matrix(1, 8).reshape(-1)
    idx, scores = topk_ip(query, matrix, k=10)
    assert idx.shape == (2,)
    assert scores.shape == (2,)


@pytest.mark.skipif(not opencl_available(), reason="OpenCL not available")
def test_opencl_and_numpy_outputs_agree():
    """When OpenCL is present, GPU and CPU paths should match."""
    matrix = _random_matrix(128, 32)
    query = _random_matrix(1, 32).reshape(-1)

    set_enabled(False)
    cpu_norm = normalize(matrix)
    cpu_dot = batch_dot(query, matrix)
    cpu_cos = batch_cosine(query, matrix)
    cpu_idx, cpu_scores = topk_ip(query, matrix, k=5)

    set_enabled(True)
    gpu_norm = normalize(matrix)
    gpu_dot = batch_dot(query, matrix)
    gpu_cos = batch_cosine(query, matrix)
    gpu_idx, gpu_scores = topk_ip(query, matrix, k=5)

    np.testing.assert_allclose(gpu_norm, cpu_norm, rtol=1e-4)
    np.testing.assert_allclose(gpu_dot, cpu_dot, rtol=1e-4)
    np.testing.assert_allclose(gpu_cos, cpu_cos, rtol=1e-4)
    np.testing.assert_array_equal(gpu_idx, cpu_idx)
    np.testing.assert_allclose(gpu_scores, cpu_scores, rtol=1e-4)
