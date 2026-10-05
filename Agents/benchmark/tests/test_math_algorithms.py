"""Tests for the math-agent algorithm catalog and the five newest pillars kernels."""

from __future__ import annotations

import numpy as np
import pytest
from algorithms import Pillar, by_pillar, catalog, get, search
from algorithms.equations import stormer_verlet_integrate
from algorithms.errors import AlgorithmInputError, AlgorithmNotFoundError
from algorithms.formula import cramer_rao_bound
from algorithms.matrix import truncated_svd
from algorithms.vision import lucas_kanade_optical_flow, pinhole_project, solve_pnp_dlt


def test_catalog_registers_every_pillar_and_new_entries() -> None:
    registered = catalog()
    assert len(registered) >= 80
    for pillar in Pillar:
        assert len(by_pillar(pillar)) > 0
    for algorithm_id in (
        "stormer_verlet_integrate",
        "solve_pnp_dlt",
        "lucas_kanade_optical_flow",
        "truncated_svd",
        "cramer_rao_bound",
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
    shift_x, shift_y = 2.0, -1.0
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
