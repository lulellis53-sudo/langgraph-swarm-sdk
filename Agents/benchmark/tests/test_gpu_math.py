"""Tests for the GPU math dispatcher and its NumPy fallback."""

from __future__ import annotations

import hypothesis.strategies as st
import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis.extra.numpy import arrays
from swarm_sdk import math as sm
from swarm_sdk.gpu import (
    batch_cosine,
    batch_dot,
    batch_softmax,
    binary_dot,
    binary_quantize,
    dequant_dot,  # type: ignore[attr-defined]
    l2_norm,
    normalize,
    normalize_dot,  # type: ignore[attr-defined]
    opencl_available,
    quantize_int8,  # type: ignore[attr-defined]
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


def test_normalize_dot_matches_cosine() -> None:
    m = _random_matrix(20, 16)
    q = _random_matrix(1, 16)[0]
    np.testing.assert_allclose(normalize_dot(q, m), batch_cosine(q, m), rtol=1e-5, atol=1e-6)


def test_normalize_dot_zero_row_scores_zero() -> None:
    m = np.zeros((2, 4), dtype=np.float32)
    m[1] = [1, 0, 0, 0]
    q = np.array([1, 0, 0, 0], dtype=np.float32)
    scores = normalize_dot(q, m)
    assert scores[0] == 0.0
    assert scores[1] == pytest.approx(1.0)


def test_quantize_int8_roundtrip_error_is_small() -> None:
    m = _random_matrix(30, 32)
    codes, scales = quantize_int8(m)
    assert codes.dtype == np.int8 and scales.dtype == np.float32
    assert codes.shape == m.shape and scales.shape == (30,)
    restored = codes.astype(np.float32) * scales[:, None]
    assert np.max(np.abs(restored - m)) <= np.max(np.abs(m)) / 127.0 + 1e-6


def test_quantize_int8_zero_row() -> None:
    codes, scales = quantize_int8(np.zeros((1, 8), dtype=np.float32))
    assert not codes.any()
    assert scales[0] == 1.0


def test_dequant_dot_close_to_float_dot() -> None:
    m = _random_matrix(40, 24)
    q = _random_matrix(1, 24)[0]
    codes, scales = quantize_int8(m)
    assert np.max(np.abs(dequant_dot(codes, scales, q) - m @ q)) < 0.15


def test_dequant_dot_single_row() -> None:
    m = _random_matrix(1, 5)
    codes, scales = quantize_int8(m)
    assert dequant_dot(codes, scales, m[0]).shape == (1,)


def test_normalize_dot_zero_query_scores_zero() -> None:
    m = _random_matrix(3, 4)
    assert not normalize_dot(np.zeros(4, dtype=np.float32), m).any()


def test_binary_quantize_packs_signs() -> None:
    m = np.array([[1.0, -1.0, 0.0, -0.5] + [1.0] * 28 + [-1.0]], dtype=np.float32)
    bits = binary_quantize(m)
    assert bits.dtype == np.uint32 and bits.shape == (1, 2)
    assert bits[0, 0] & 1 == 1
    assert (bits[0, 0] >> 1) & 1 == 0
    assert (bits[0, 0] >> 2) & 1 == 1
    assert bits[0, 1] == 0


def test_binary_dot_identical_is_dim() -> None:
    m = _random_matrix(5, 40)
    bits = binary_quantize(m)
    scores = binary_dot(bits, bits[2], dim=40)
    assert scores[2] == 40.0
    assert scores.argmax() == 2


def test_binary_dot_opposite_is_zero() -> None:
    v = np.linspace(-1, 1, 33, dtype=np.float32).reshape(1, -1)
    v[v == 0] = 0.5
    assert binary_dot(binary_quantize(v), binary_quantize(-v)[0], dim=33)[0] == 0.0


def test_binary_dot_dim_not_multiple_of_32_ignores_padding() -> None:
    bits = binary_quantize(np.ones((1, 5), dtype=np.float32))
    assert binary_dot(bits, bits[0], dim=5)[0] == 5.0


def test_binary_dot_preserves_neighbor_order() -> None:
    rng = np.random.default_rng(3)
    base = rng.standard_normal((1, 256)).astype(np.float32)
    near = base + 0.05 * rng.standard_normal((1, 256)).astype(np.float32)
    far = rng.standard_normal((1, 256)).astype(np.float32)
    bits = binary_quantize(np.vstack([far, near]))
    scores = binary_dot(bits, binary_quantize(base)[0], dim=256)
    assert scores[1] > scores[0]


def test_batch_softmax_sums_to_one_and_is_stable() -> None:
    p = batch_softmax(np.array([1000.0, 1001.0, 999.0], dtype=np.float32))
    assert p.sum() == pytest.approx(1.0, abs=1e-6)
    assert p.argmax() == 1
    assert np.isfinite(p).all()


def test_batch_softmax_single_and_empty() -> None:
    assert batch_softmax(np.array([3.0], dtype=np.float32))[0] == pytest.approx(1.0)
    assert batch_softmax(np.array([], dtype=np.float32)).size == 0


@pytest.fixture()
def _opencl_all_rows(monkeypatch: pytest.MonkeyPatch):
    """Route every row count to the GPU so the 2D kernels are exercised."""
    monkeypatch.setenv("SWARM_OPENCL_MIN_ROWS", "1")
    if not opencl_available():
        pytest.skip("OpenCL not available")
    set_enabled(True)
    yield
    set_enabled(False)


@pytest.mark.usefixtures("_opencl_all_rows")
def test_opencl_batch_dot_matches_numpy_odd_and_padded_columns() -> None:
    for rows, cols in ((97, 30), (5, 2), (64, 4), (33, 128)):
        matrix = _random_matrix(rows, cols)
        query = _random_matrix(1, cols).reshape(-1)
        np.testing.assert_allclose(batch_dot(query, matrix), matrix @ query, rtol=1e-4, atol=1e-5)


@pytest.mark.usefixtures("_opencl_all_rows")
def test_opencl_normalize_and_cosine_match_numpy() -> None:
    matrix = _random_matrix(70, 44)
    query = _random_matrix(1, 44).reshape(-1)
    expected_norms = np.linalg.norm(matrix, axis=1).astype(np.float32)
    np.testing.assert_allclose(l2_norm(matrix), expected_norms, rtol=1e-4)
    cosine = batch_cosine(query, matrix)
    np.testing.assert_allclose(normalize_dot(query, matrix), cosine, rtol=1e-4, atol=1e-5)
    norms = np.linalg.norm(normalize(matrix), axis=1)
    np.testing.assert_allclose(norms, np.ones(70), rtol=1e-4)


@pytest.mark.usefixtures("_opencl_all_rows")
def test_opencl_int8_and_binary_match_numpy() -> None:
    matrix = _random_matrix(129, 64)
    query = _random_matrix(1, 64).reshape(-1)
    codes, scales = quantize_int8(matrix)
    expected = (codes.astype(np.float32) @ query) * scales
    np.testing.assert_allclose(dequant_dot(codes, scales, query), expected, rtol=1e-3, atol=1e-4)

    bits = binary_quantize(matrix)
    query_bits = binary_quantize(query)[0]
    xor = np.bitwise_xor(bits, query_bits[None, :])
    distance = np.unpackbits(xor.view(np.uint8), axis=1).sum(axis=1)
    np.testing.assert_allclose(
        binary_dot(bits, query_bits, dim=64), (64 - distance).astype(np.float32)
    )


@pytest.mark.usefixtures("_opencl_all_rows")
def test_opencl_cached_buffers_track_generation_changes() -> None:
    from swarm_sdk.memory.opencl_store import OpenClVecStore

    store = OpenClVecStore(8, max_vectors=4, chunk_rows=4)
    for i in range(4):
        row = np.zeros(8, dtype=np.float32)
        row[i] = 1.0
        store.add(f"v{i}", row)
    hits = store.search(np.eye(8, dtype=np.float32)[0], 1)
    assert hits[0].id == 0
    store.add("newer", np.eye(8, dtype=np.float32)[1])
    hits = store.search(np.eye(8, dtype=np.float32)[1], 1)
    assert hits[0].id == 4


def test_batch_softmax_matches_symbolic_helper() -> None:
    scores = np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float32)
    expected = np.array(sm.softmax_scores(scores.tolist()), dtype=np.float32)
    np.testing.assert_allclose(batch_softmax(scores), expected, rtol=1e-6)


def test_quantize_int8_matches_symbolic_helper() -> None:
    matrix = np.array([[0.0, 63.5, -127.0], [254.0, -254.0, 1.0]], dtype=np.float32)
    codes, scales = quantize_int8(matrix)
    for i in range(matrix.shape[0]):
        expected_scale = sm.int8_scale(float(np.abs(matrix[i]).max()))
        assert scales[i] == pytest.approx(expected_scale)
        for j in range(matrix.shape[1]):
            expected_code = sm.int8_quantize(float(matrix[i, j]), expected_scale)
            assert int(codes[i, j]) == expected_code


def test_binary_cosine_matches_symbolic_estimate() -> None:
    dim = 64
    query = np.random.default_rng(7).standard_normal(dim).astype(np.float32)
    matrix = np.random.default_rng(8).standard_normal((10, dim)).astype(np.float32)
    query_bits = binary_quantize(query)[0]
    bits = binary_quantize(matrix)
    scores = binary_dot(bits, query_bits, dim=dim)
    for row, score in enumerate(scores):
        hamming = dim - int(score)
        expected = sm.binary_cosine_estimate(hamming, dim)
        assert expected == pytest.approx(np.cos(np.pi * hamming / dim), abs=1e-5)
    # The OpenCL store converts binary scores back to cosine estimates with float32
    # arithmetic; compare against a float32 cosine, not a float64 one.
    np.testing.assert_allclose(
        np.cos(np.pi * (dim - scores) / dim).astype(np.float32),
        np.array([sm.binary_cosine_estimate(int(dim - s), dim) for s in scores], dtype=np.float32),
        rtol=1e-4,
        atol=1e-6,
    )


def test_l2_norm_matches_symbolic_helper() -> None:
    matrix = np.array([[3.0, 4.0], [0.0, 0.0], [1.0, 2.0]], dtype=np.float32)
    norms = l2_norm(matrix)
    for i, norm in enumerate(norms):
        row = [float(matrix[i, j]) for j in range(matrix.shape[1])]
        assert norm == pytest.approx(sm.l2_norm(row), rel=1e-5)


def test_batch_cosine_matches_symbolic_helper() -> None:
    rng = np.random.default_rng(9)
    matrix = rng.standard_normal((5, 8)).astype(np.float32)
    query = rng.standard_normal(8).astype(np.float32)
    scores = batch_cosine(query, matrix)
    expected = np.array(
        [sm.cosine_similarity(query.tolist(), row.tolist()) for row in matrix],
        dtype=np.float32,
    )
    np.testing.assert_allclose(scores, expected, rtol=1e-5, atol=1e-6)
