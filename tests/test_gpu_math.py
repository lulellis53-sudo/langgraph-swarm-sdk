"""Tests for the GPU math dispatcher and its NumPy fallback."""

from __future__ import annotations

import hypothesis.strategies as st
import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis.extra.numpy import arrays

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

_FINITE_F32 = st.floats(
    min_value=-2.0,
    max_value=2.0,
    width=32,
    allow_nan=False,
    allow_infinity=False,
)


def _matrix_strategy(*, max_rows: int = 12, max_cols: int = 16):
    return arrays(
        dtype=np.float32,
        shape=st.tuples(st.integers(1, max_rows), st.integers(2, max_cols)),
        elements=_FINITE_F32,
    )


def _random_matrix(rows: int, cols: int) -> np.ndarray:
    rng = np.random.default_rng(42)
    return rng.standard_normal((rows, cols)).astype(np.float32)


@pytest.fixture(autouse=True)
def _disable_opencl_for_cpu_fallback():
    """Most tests run against the NumPy fallback so they pass without pyopencl."""
    set_enabled(False)
    yield
    set_enabled(True)
    reset_opencl()


@given(matrix=_matrix_strategy())
@settings(max_examples=40, deadline=None)
def test_l2_norm_matches_numpy(matrix: np.ndarray) -> None:
    expected = np.linalg.norm(matrix, axis=1).astype(np.float32)
    np.testing.assert_allclose(l2_norm(matrix), expected, rtol=1e-5, atol=1e-6)


@given(matrix=_matrix_strategy())
@settings(max_examples=40, deadline=None)
def test_normalize_unit_or_zero(matrix: np.ndarray) -> None:
    normalized = normalize(matrix)
    assert not np.any(np.isnan(normalized))
    norms = np.linalg.norm(normalized, axis=1)
    original = np.linalg.norm(matrix, axis=1)
    # Only assert unit length for rows that are clearly non-degenerate in float32.
    mask = original > 1e-6
    if np.any(mask):
        np.testing.assert_allclose(norms[mask], 1.0, rtol=1e-4, atol=1e-5)


@given(data=_matrix_strategy(max_rows=10, max_cols=12))
@settings(max_examples=35, deadline=None)
def test_batch_dot_and_cosine_match_numpy(data: np.ndarray) -> None:
    matrix = data
    query = data[0]
    np.testing.assert_allclose(batch_dot(query, matrix), matrix @ query, rtol=1e-5, atol=1e-6)

    q_norm = float(np.linalg.norm(query)) or 1.0
    m_norm = np.linalg.norm(matrix, axis=1)
    m_norm = np.where(m_norm == 0, 1.0, m_norm)
    manual = (matrix @ query) / (m_norm * q_norm)
    np.testing.assert_allclose(batch_cosine(query, matrix), manual, rtol=1e-5, atol=1e-6)


@given(data=_matrix_strategy(max_rows=10, max_cols=12), k=st.integers(1, 8))
@settings(max_examples=30, deadline=None)
def test_topk_ip_scores_descending_and_match_rows(data: np.ndarray, k: int) -> None:
    matrix = data
    query = data[0]
    idx, scores = topk_ip(query, matrix, k=k)
    assert len(idx) == len(scores) == min(k, matrix.shape[0])
    assert np.all(np.diff(scores) <= 1e-5)
    expected = matrix @ query
    for i, score in zip(idx, scores, strict=True):
        assert pytest.approx(float(score), rel=1e-4, abs=1e-5) == float(expected[int(i)])


def test_normalize_preserves_zero_vectors() -> None:
    matrix = np.zeros((4, 8), dtype=np.float32)
    np.testing.assert_array_equal(normalize(matrix), matrix)


def test_topk_ip_clamps_to_available_rows() -> None:
    matrix = _random_matrix(2, 8)
    query = _random_matrix(1, 8).reshape(-1)
    idx, scores = topk_ip(query, matrix, k=10)
    assert idx.shape == (2,)
    assert scores.shape == (2,)


@pytest.mark.skipif(not opencl_available(), reason="OpenCL not available")
def test_opencl_and_numpy_outputs_agree() -> None:
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
