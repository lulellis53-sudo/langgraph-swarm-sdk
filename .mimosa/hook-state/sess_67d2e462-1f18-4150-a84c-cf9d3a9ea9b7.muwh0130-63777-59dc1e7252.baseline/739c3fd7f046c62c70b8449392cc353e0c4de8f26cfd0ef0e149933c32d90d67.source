"""Tests for the math-agent algorithm catalog and the newest pillars kernels."""

from __future__ import annotations

import math

import numpy as np
import pytest
from algorithms import Pillar, by_pillar, catalog, get, search
from algorithms.compute import cache_aware_tile_size
from algorithms.equations import bisection_root, stormer_verlet_integrate
from algorithms.errors import AlgorithmError, AlgorithmInputError, AlgorithmNotFoundError
from algorithms.formula import cramer_rao_bound, sigmoid_stable, softmax_stable
from algorithms.matrix import conjugate_gradient, power_iteration, truncated_svd
from algorithms.vector import topk_inner_product
from algorithms.vision import (
    lucas_kanade_optical_flow,
    pinhole_project,
    solve_pnp_dlt,
    triangulate_point_dlt,
)


def test_catalog_registers_every_pillar_and_new_entries() -> None:
    registered = catalog()
    assert len(registered) >= 90
    for pillar in Pillar:
        assert len(by_pillar(pillar)) > 0
    for algorithm_id in (
        "stormer_verlet_integrate",
        "solve_pnp_dlt",
        "lucas_kanade_optical_flow",
        "truncated_svd",
        "cramer_rao_bound",
        "topk_inner_product",
        "cache_aware_tile_size",
        "bisection_root",
        "triangulate_point_dlt",
        "conjugate_gradient",
        "power_iteration",
        "softmax_stable",
        "sigmoid_stable",
    ):
        entry = get(algorithm_id)
        assert entry.id == algorithm_id and callable(entry.function)
    assert search("verlet")
    with pytest.raises(AlgorithmNotFoundError):
        get("missing_algorithm")


def test_stormer_verlet_conserves_harmonic_oscillator_energy() -> None:
    def grad_potential(q: np.ndarray) -> np.ndarray:
        return q

    q_traj, p_traj = stormer_verlet_integrate(
        np.array([1.0, 0.0]), np.array([0.0, 1.0]), grad_potential, dt=0.01, steps=2000
    )
    energy = 0.5 * np.sum(p_traj**2 + q_traj**2, axis=1)
    drift = float(np.max(np.abs(energy - energy[0])))
    assert drift < 1e-4, f"energy drift {drift} exceeds the O(dt^2) bound"
    with pytest.raises(AlgorithmInputError):
        stormer_verlet_integrate(np.zeros(2), np.zeros(2), grad_potential, dt=-1.0, steps=5)


def test_solve_pnp_dlt_recovers_known_pose() -> None:
    rng = np.random.default_rng(7)
    intrinsics = np.array(
        [[800.0, 0.0, 320.0], [0.0, 800.0, 240.0], [0.0, 0.0, 1.0]], dtype=np.float64
    )
    theta = 0.3
    rotation = np.array(
        [
            [np.cos(theta), 0.0, np.sin(theta)],
            [0.0, 1.0, 0.0],
            [-np.sin(theta), 0.0, np.cos(theta)],
        ]
    )
    translation = np.array([0.1, -0.2, 5.0])
    world = rng.uniform(-1.0, 1.0, size=(40, 3))
    world[:, 2] += 4.0
    image = pinhole_project(world, intrinsics, rotation, translation)
    estimated_r, estimated_t = solve_pnp_dlt(world, image, intrinsics)
    reprojection = pinhole_project(world, intrinsics, estimated_r, estimated_t)
    assert float(np.linalg.norm(reprojection - image, axis=1).max()) < 1e-6
    assert np.allclose(estimated_r.T @ estimated_r, np.eye(3), atol=1e-10)
    assert abs(np.linalg.det(estimated_r) - 1.0) < 1e-10
    scale = float(translation @ estimated_t) / float(estimated_t @ estimated_t)
    assert abs(scale - 1.0) < 1e-9
    assert float(np.linalg.norm(translation - scale * estimated_t)) < 1e-6


def test_lucas_kanade_recovers_translation() -> None:
    yy, xx = np.mgrid[0:64, 0:64]
    base = np.sin(xx / 5.0) * np.cos(yy / 7.0) + 0.1 * np.sin(3.0 * xx / 4.0)
    shift_x, shift_y = 1.0, -1.0
    shifted = np.roll(np.roll(base, int(shift_x), axis=1), int(shift_y), axis=0)
    flow = lucas_kanade_optical_flow(base, shifted, window_size=11)
    center = flow[24:40, 24:40]
    magnitude = np.linalg.norm(center, axis=2)
    trusted = magnitude > 1e-6
    assert trusted.any(), "no pixel produced a trusted flow"
    estimate = center[trusted].mean(axis=0)
    assert abs(estimate[0] - shift_x) < 0.2
    assert abs(estimate[1] - shift_y) < 0.2


def test_truncated_svd_matches_eckart_young_errors() -> None:
    rng = np.random.default_rng(3)
    matrix = rng.standard_normal((12, 8)) @ np.diag(np.linspace(9.0, 1.0, 8))
    singular = np.linalg.svd(matrix, compute_uv=False)
    result = truncated_svd(matrix, rank=3)
    spectral = float(np.linalg.norm(matrix - result["approx"], 2))
    frobenius = float(np.linalg.norm(matrix - result["approx"], "fro"))
    assert abs(spectral - result["spectral_error"]) < 1e-9
    assert abs(spectral - singular[3]) < 1e-9
    expected_fro = float(np.sqrt(np.sum(singular[3:] ** 2)))
    assert abs(frobenius - result["frobenius_error"]) < 1e-9
    assert abs(frobenius - expected_fro) < 1e-9
    with pytest.raises(AlgorithmInputError):
        truncated_svd(matrix, rank=0)


def test_cramer_rao_bound_for_gaussian_mean() -> None:
    sigma = 0.5
    samples = 25
    information = samples / sigma**2
    assert abs(cramer_rao_bound(information) - sigma**2 / samples) < 1e-12
    matrix = np.array([[4.0, 1.0], [1.0, 2.0]])
    inverse = cramer_rao_bound(matrix)
    assert np.allclose(inverse @ matrix, np.eye(2), atol=1e-12)
    with pytest.raises(AlgorithmInputError):
        cramer_rao_bound(-1.0)
    with pytest.raises(AlgorithmInputError):
        cramer_rao_bound(np.array([[1.0, 2.0], [2.0, 1.0]]))


def test_topk_inner_product_matches_full_argsort() -> None:
    rows = np.arange(40.0).reshape((10, 4)) / 10.0
    query = np.array([1.0, -0.5, 2.0, 0.25])
    expected = sorted(((float(row @ query), i) for i, row in enumerate(rows)), reverse=True)
    result = topk_inner_product(rows, query, 3)
    assert len(result) == 3
    for (score, index), (want, want_index) in zip(result, expected[:3], strict=True):
        assert abs(score - want) < 1e-12
        assert index == want_index
    assert len(topk_inner_product(rows, query, 10)) == 10
    with pytest.raises(AlgorithmInputError):
        topk_inner_product(rows, query, 11)


def test_cache_aware_tile_size_keeps_three_tiles_in_cache() -> None:
    assert cache_aware_tile_size(32768, element_bytes=8) == 36
    assert cache_aware_tile_size(24, element_bytes=8) == 1
    with pytest.raises(AlgorithmInputError):
        cache_aware_tile_size(0)


def test_bisection_root_finds_dottie_number() -> None:
    root = bisection_root(lambda x: math.cos(x) - x, 0.0, 1.0, tol=1e-12, max_iter=100)
    assert abs(root - 0.7390851332151607) < 1e-10
    with pytest.raises(AlgorithmInputError):
        bisection_root(math.cos, 0.0, 0.5)
    with pytest.raises(AlgorithmError):
        bisection_root(lambda x: math.cos(x) - x, 0.0, 1.0, tol=1e-12, max_iter=2)


def test_triangulate_point_dlt_recovers_world_point() -> None:
    intrinsics = np.eye(3, dtype=np.float64)
    theta = 0.4
    rotation = np.array(
        [
            [np.cos(theta), 0.0, np.sin(theta)],
            [0.0, 1.0, 0.0],
            [-np.sin(theta), 0.0, np.cos(theta)],
        ]
    )
    camera1 = intrinsics @ np.hstack([np.eye(3), np.zeros((3, 1))])
    camera2 = intrinsics @ np.hstack([rotation, np.array([[2.0], [0.0], [0.0]])])
    world = np.array([0.5, -0.3, 4.0])
    image1 = pinhole_project(world[None, :], intrinsics, np.eye(3), np.zeros(3))[0]
    image2 = pinhole_project(world[None, :], intrinsics, rotation, np.array([2.0, 0.0, 0.0]))[0]
    recovered = triangulate_point_dlt(camera1, camera2, image1, image2)
    assert np.allclose(recovered, world, atol=1e-9)
    with pytest.raises(AlgorithmInputError):
        triangulate_point_dlt(np.eye(3), camera2, image1, image2)


def test_conjugate_gradient_solves_spd_system() -> None:
    rng = np.random.default_rng(11)
    base = rng.standard_normal((30, 30))
    matrix = base @ base.T + 30.0 * np.eye(30)
    rhs = rng.standard_normal(30)
    solution = conjugate_gradient(matrix, rhs, tol=1e-12)
    direct = np.linalg.solve(matrix, rhs)
    assert np.allclose(solution, direct, atol=1e-7)
    assert float(np.linalg.norm(matrix @ solution - rhs)) < 1e-9 * float(np.linalg.norm(rhs))
    with pytest.raises(AlgorithmError):
        conjugate_gradient(matrix, rhs, tol=1e-12, max_iter=1)


def test_power_iteration_finds_dominant_eigenpair() -> None:
    matrix = np.diag([5.0, 3.0, 1.0])
    eigenvalue, vector = power_iteration(matrix)
    assert abs(eigenvalue - 5.0) < 1e-9
    assert abs(abs(vector[0]) - 1.0) < 1e-9
    with pytest.raises(AlgorithmError):
        power_iteration(np.diag([5.0, 3.0, 1.0]), max_iter=1)


def test_softmax_and_sigmoid_are_stable_at_extreme_logits() -> None:
    extreme = np.array([1000.0, 1000.0, 0.0, -1000.0])
    probabilities = softmax_stable(extreme)
    assert np.all(np.isfinite(probabilities))
    assert abs(probabilities.sum() - 1.0) < 1e-12
    assert abs(probabilities[0] - 0.5) < 1e-12
    assert probabilities[2] < 1e-12 and probabilities[3] < 1e-12
    moderate = np.array([1.0, 2.0, 3.0])
    weights = np.exp(moderate)
    assert np.allclose(softmax_stable(moderate), weights / weights.sum())
    with pytest.raises(AlgorithmInputError):
        softmax_stable(np.array([np.inf, 0.0]))
    for value in (0.0, 30.0, -30.0):
        assert abs(sigmoid_stable(value) - 1.0 / (1.0 + math.exp(-value))) < 1e-12
    with np.errstate(over="ignore"):
        for value in (1000.0, -1000.0):
            expected = 1.0 / (1.0 + np.exp(-value))
            assert abs(sigmoid_stable(value) - expected) < 1e-15
    array_result = sigmoid_stable(np.array([-1000.0, 0.0, 1000.0]))
    assert np.all(np.isfinite(array_result))
    assert array_result[0] < 1e-12 and array_result[2] > 1.0 - 1e-12
    assert isinstance(sigmoid_stable(1.0), float)
