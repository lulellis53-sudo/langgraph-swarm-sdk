"""Benchmark: math algorithms catalog — correctness, stability, and integrity.

Exercises the ``Agents/math`` kernels against NumPy references with tight
tolerances (Math-agent epistemic tier: [Empirically Validated]), the linear
verification gate, and catalog integrity. Run from the repo root:

    cd ~/Swarm && PYTHONPATH=Agents/math uv run --no-sync pytest \
        Agents/benchmark/Tasks/math_numerics -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "math"))

from importlib import import_module  # noqa: E402

from algorithms import compute as algo_compute  # noqa: E402
from algorithms import equations as algo_equations  # noqa: E402
from algorithms import matrix as algo_matrix  # noqa: E402
from algorithms import vector as algo_vector  # noqa: E402
from algorithms import verify as algo_verify  # noqa: E402

# algorithms/__init__ re-exports a catalog() function that shadows the submodule
# attribute, so the module must be resolved through sys.modules explicitly.
algo_catalog = import_module("algorithms.catalog")  # noqa: E402

RNG = np.random.default_rng(2026)


def test_catalog_is_populated_and_consistent() -> None:
    entries = algo_catalog.catalog()
    assert len(entries) >= 80  # measured 85 on 2026-10-06
    assert len({entry_id for entry_id in entries}) == len(entries)
    first = next(iter(entries.values()))
    assert algo_catalog.get(first.id) is first
    assert len(algo_catalog.by_pillar(first.pillar)) >= 1
    assert len(algo_catalog.search("gradient")) >= 1


def test_euclidean_distance_and_cosine_match_reference() -> None:
    left = RNG.normal(size=64)
    right = RNG.normal(size=64)
    assert algo_vector.euclidean_distance(left, right) == pytest.approx(
        float(np.linalg.norm(left - right)), rel=1e-12
    )
    unit_left = left / np.linalg.norm(left)
    assert algo_vector.cosine_similarity(unit_left, unit_left) == pytest.approx(1.0, abs=1e-12)
    assert algo_vector.cosine_similarity(unit_left, -unit_left) == pytest.approx(-1.0, abs=1e-12)


def test_mips_lift_maps_to_fixed_norm_sphere() -> None:
    from algorithms.errors import AlgorithmInputError

    vectors = RNG.normal(size=(32, 8))
    bound = 2.0 * float(np.linalg.norm(vectors, axis=1).max())
    lifted = algo_vector.mips_lift(vectors, bound=bound)
    assert lifted.shape == (32, 9)
    assert float(np.abs(np.linalg.norm(lifted, axis=1) - bound).max()) < 1e-12
    expected_extra = np.sqrt(bound**2 - np.linalg.norm(vectors, axis=1) ** 2)
    assert float(np.abs(lifted[:, -1] - expected_extra).max()) < 1e-12
    with pytest.raises(AlgorithmInputError, match="smaller than a vector norm"):
        algo_vector.mips_lift(vectors, bound=bound / 4.0)


def test_fft_matches_numpy_reference() -> None:
    signal = RNG.normal(size=256)
    ours = algo_compute.cooley_tukey_fft(signal)
    reference = np.fft.fft(signal)
    assert float(np.abs(ours - reference).max()) < 1e-8


def test_tiled_and_strassen_matmul_match_reference() -> None:
    left = RNG.normal(size=(64, 64))
    right = RNG.normal(size=(64, 64))
    reference = left @ right
    tiled = algo_compute.tiled_matmul(left, right, block_size=16)
    strassen = algo_compute.strassen_matmul(left, right, leaf=16)
    assert float(np.abs(tiled - reference).max()) < 1e-9
    assert float(np.abs(strassen - reference).max()) < 1e-8


def test_attainable_performance_roofline_bounds() -> None:
    peak_flops, bandwidth = 1e12, 100e9
    intensity, attainable, active = algo_compute.attainable_performance(
        peak_flops=peak_flops,
        bandwidth_bytes_per_second=bandwidth,
        flops=200.0,
        bytes_moved=100.0,
    )
    assert intensity == pytest.approx(2.0)
    assert active == "memory"
    assert attainable == pytest.approx(200e9)
    _, compute_bound_rate, compute_active = algo_compute.attainable_performance(
        peak_flops=peak_flops,
        bandwidth_bytes_per_second=bandwidth,
        flops=1e5,
        bytes_moved=100.0,
    )
    assert compute_active == "compute"
    assert compute_bound_rate == pytest.approx(peak_flops)


def test_householder_qr_is_orthonormal_and_reconstructs() -> None:
    matrix = RNG.normal(size=(48, 32))
    q_matrix, r_matrix = algo_matrix.householder_qr(matrix)
    rows = matrix.shape[0]
    assert q_matrix.shape == (rows, rows)  # full QR, not reduced
    assert float(np.abs(q_matrix.T @ q_matrix - np.eye(rows)).max()) < 1e-10
    assert float(np.abs(q_matrix @ r_matrix - matrix).max()) < 1e-9


def test_cholesky_reconstructs_spd_matrix() -> None:
    base = RNG.normal(size=(40, 40))
    spd = base @ base.T + 40 * np.eye(40)
    lower = algo_matrix.cholesky_factorization(spd)
    assert float(np.abs(lower @ lower.T - spd).max()) < 1e-8


def test_condition_number_matches_numpy() -> None:
    matrix = RNG.normal(size=(24, 24)) + 24 * np.eye(24)
    assert algo_matrix.condition_number_2(matrix) == pytest.approx(
        float(np.linalg.cond(matrix, 2)), rel=1e-6
    )


def test_damped_newton_solves_nonlinear_system() -> None:
    def residual(point: np.ndarray) -> np.ndarray:
        return np.array([point[0] ** 2 + point[1] - 3.0, point[0] + point[1] ** 2 - 5.0])

    def jacobian(point: np.ndarray) -> np.ndarray:
        return np.array([[2 * point[0], 1.0], [1.0, 2 * point[1]]])

    root = algo_equations.damped_newton_root(residual, jacobian, np.array([1.0, 1.5]))
    assert float(np.abs(residual(root)).max()) < 1e-10


def test_verification_gate_accepts_exact_and_rejects_corrupt() -> None:
    matrix = RNG.normal(size=(16, 16)) + 16 * np.eye(16)
    rhs = RNG.normal(size=16)
    solution = np.linalg.solve(matrix, rhs)
    exact = algo_verify.verify_numerical_solution(matrix, rhs, solution)
    assert exact["passed"] is True
    assert exact["condition_number"] == pytest.approx(float(np.linalg.cond(matrix, 2)), rel=1e-6)
    corrupt = algo_verify.verify_numerical_solution(matrix, rhs, solution + 1e3)
    assert corrupt["passed"] is False
