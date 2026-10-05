"""Behavior tests for the math-agent algorithm database."""

import numpy as np
import pytest
from algorithms import (
    AlgorithmDependencyError,
    AlgorithmInputError,
    AlgorithmNotFoundError,
    NotPositiveDefiniteError,
    Pillar,
    by_pillar,
    call,
    catalog,
    get,
    search,
)


def test_catalog_covers_every_pillar_once() -> None:
    """Every registered id is unique and each pillar has at least one algorithm."""
    records = catalog()
    assert len(records) == 80
    assert len({item.id for item in records.values()}) == 80
    assert get("factorial").source.endswith("maths/factorial.py")
    assert get("arrow_mean").source.endswith("maths/average_mean.py")
    for pillar in Pillar:
        assert by_pillar(pillar)
        assert by_pillar(int(pillar)) == by_pillar(pillar)
    assert get("householder_qr").id == "householder_qr"
    assert search("homography")[0].id == "compute_homography_dlt"


def test_unknown_lookup_and_pillar_fail() -> None:
    """Missing ids and pillar numbers raise the database errors."""
    with pytest.raises(AlgorithmNotFoundError):
        get("not-an-algorithm")
    with pytest.raises(AlgorithmInputError):
        by_pillar(0)
    with pytest.raises(AlgorithmInputError):
        search("   ")


def test_sq8_reconstruction_stays_inside_half_a_bin() -> None:
    """Uniform SQ8 reconstruction error is at most half the bin width."""
    sample = np.linspace(-2.0, 3.0, 51)
    codes, reconstructed, low, delta = call("sq8_encode_decode", sample)
    assert codes.dtype == np.uint8
    assert low == pytest.approx(-2.0)
    assert np.max(np.abs(reconstructed - sample)) <= delta / 2.0 + 1e-6


def test_metric_identities_and_hnsw() -> None:
    """Unit-vector identity, MIPS lift, and a path-graph search hold."""
    left = np.array([1.0, 0.0])
    right = np.array([0.0, 1.0])
    distance = call("euclidean_distance", left, right)
    cosine = call("cosine_similarity", left, right)
    assert distance**2 == pytest.approx(2.0 * (1.0 - cosine))
    lifted = call("mips_lift", np.array([[3.0, 4.0], [0.0, 0.0]]))
    assert np.linalg.norm(lifted, axis=1) == pytest.approx([5.0, 5.0])
    assert call(
        "hamming_angular_cosine", np.array([1, 1, 0]), np.array([1, 0, 0])
    ) == pytest.approx(np.cos(np.pi / 3.0))
    vectors = np.arange(10, dtype=float)[:, None]
    graph = {i: [j for j in (i - 1, i + 1) if 0 <= j < 10] for i in range(10)}
    found = call("hnsw_greedy_search", np.array([5.1]), 0, graph, vectors, 3)
    assert found[0][1] == 5


def test_pq_codebook_shape_is_deterministic() -> None:
    """A seeded Lloyd run returns one centroid block per subspace."""
    rng = np.random.default_rng(7)
    data = rng.normal(size=(40, 8)).astype(np.float32)
    books = call(
        "train_ivf_pq_codebooks",
        data,
        4,
        3,
        iterations=2,
        rng=np.random.default_rng(7),
    )
    again = call(
        "train_ivf_pq_codebooks",
        data,
        4,
        3,
        iterations=2,
        rng=np.random.default_rng(7),
    )
    assert books.shape == (4, 3, 2)
    assert np.array_equal(books, again)


def test_matmul_fft_and_roofline() -> None:
    """Tiled and Strassen products match NumPy, and the FFT matches its DFT."""
    rng = np.random.default_rng(1)
    left = rng.normal(size=(5, 3))
    right = rng.normal(size=(3, 4))
    assert call("tiled_matmul", left, right, 2) == pytest.approx(left @ right)
    square_left = rng.normal(size=(8, 8))
    square_right = rng.normal(size=(8, 8))
    assert call("strassen_matmul", square_left, square_right, leaf=2) == pytest.approx(
        square_left @ square_right
    )
    signal = rng.normal(size=16)
    assert call("cooley_tukey_fft", signal) == pytest.approx(np.fft.fft(signal))
    intensity, rate, bound = call("attainable_performance", 100.0, 10.0, 50.0, 10.0)
    assert intensity == pytest.approx(5.0)
    assert rate == pytest.approx(50.0)
    assert bound == "memory"


def test_damped_newton_finds_square_root() -> None:
    """Damped Newton solves x^2 - 2 = 0 from a positive start."""

    def residual(point: np.ndarray) -> np.ndarray:
        return np.array([point[0] ** 2 - 2.0])

    def jacobian(point: np.ndarray) -> np.ndarray:
        return np.array([[2.0 * point[0]]])

    root = call("damped_newton_root", residual, jacobian, np.array([1.0]))
    assert root[0] == pytest.approx(np.sqrt(2.0))


def test_bm25_invariants_are_proved() -> None:
    """SymPy confirms the two BM25 term-frequency claims."""
    proved = call("verify_bm25_asymptotics")
    assert proved == {
        "monotonic_in_tf": True,
        "saturation_limit_is_k1_plus_1": True,
    }


def test_vision_geometry() -> None:
    """Homography, epipolar residual, Sobel, and pinhole projection match their models."""
    rng = np.random.default_rng(3)
    true_h = np.array([[1.2, 0.1, 3.0], [0.0, 0.8, -1.0], [0.0001, 0.0002, 1.0]])
    source = rng.normal(size=(8, 2))
    homogeneous = np.column_stack([source, np.ones(len(source))])
    mapped = (true_h @ homogeneous.T).T
    destination = mapped[:, :2] / mapped[:, 2:3]
    estimated = call("compute_homography_dlt", source, destination)
    assert estimated == pytest.approx(true_h / true_h[2, 2], abs=1e-8)

    world = rng.normal(size=(20, 3)) + np.array([0.0, 0.0, 5.0])
    pose = np.array([[1.0, 0.0, 0.0, 0.2], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0]])

    def project(matrix: np.ndarray, points: np.ndarray) -> np.ndarray:
        lifted = np.column_stack([points, np.ones(len(points))])
        image = (matrix @ lifted.T).T
        return image[:, :2] / image[:, 2:3]

    first = project(np.eye(3, 4), world)
    second = project(pose, world)
    fundamental = call("fundamental_matrix_8point", first, second)
    fundamental = fundamental / np.linalg.norm(fundamental)
    ones = np.ones((len(first), 1))
    x1 = np.hstack([first, ones])
    x2 = np.hstack([second, ones])
    residual = np.abs(np.sum(x2 * (fundamental @ x1.T).T, axis=1))
    assert np.max(residual) < 1e-8

    image = np.zeros((5, 5))
    assert call("sobel_gradients_2d", image)[2] == pytest.approx(np.zeros((5, 5)))
    pixels = call(
        "pinhole_project",
        np.array([[0.0, 0.0, 2.0]]),
        np.eye(3),
        np.eye(3),
        np.zeros(3),
    )
    assert pixels == pytest.approx(np.array([[0.0, 0.0]]))


def test_factorizations_sparse_product_and_linear_check() -> None:
    """QR, Cholesky, CSR, and the residual gate match dense linear algebra."""
    rng = np.random.default_rng(4)
    matrix = rng.normal(size=(6, 4))
    orthogonal, upper = call("householder_qr", matrix)
    assert orthogonal.T @ orthogonal == pytest.approx(np.eye(6))
    assert orthogonal @ upper == pytest.approx(matrix)

    factor_source = rng.normal(size=(4, 4))
    spd = factor_source.T @ factor_source + np.eye(4)
    factor = call("cholesky_factorization", spd)
    assert factor @ factor.T == pytest.approx(spd)
    with pytest.raises(NotPositiveDefiniteError):
        call("cholesky_factorization", np.array([[1.0, 2.0], [2.0, 1.0]]))

    dense = np.array([[1.0, 0.0, 2.0], [0.0, 3.0, 0.0]])
    values = np.array([1.0, 2.0, 3.0])
    indices = np.array([0, 2, 1])
    indptr = np.array([0, 2, 3])
    vector = np.array([4.0, 5.0, 6.0])
    assert call("spmv_csr", values, indices, indptr, vector) == pytest.approx(dense @ vector)

    solution = np.linalg.solve(spd, np.arange(4, dtype=float))
    report = call("verify_numerical_solution", spd, np.arange(4, dtype=float), solution)
    assert report["passed"] is True
    assert report["condition_number"] == pytest.approx(call("condition_number_2", spd))


def test_formula_shields_quadrature_and_updates() -> None:
    """Stable rewrites, quadrature, and the two inversion lemmas match their identities."""
    large = 1e16
    naive = np.sqrt(large + 1.0) - np.sqrt(large)
    stable = call("sqrt_diff_stable", large)
    truth = 1.0 / (np.sqrt(large + 1.0) + np.sqrt(large))
    assert stable == pytest.approx(truth)
    assert abs(stable - truth) <= abs(naive - truth)

    tiny = 1e-8
    series = tiny**2 / 2.0 - tiny**4 / 24.0
    assert call("one_minus_cos", tiny) == pytest.approx(series, rel=1e-12)
    assert call("log1p_stable", 1e-10) == pytest.approx(np.log1p(1e-10))
    assert call("expm1_stable", 1e-10) == pytest.approx(np.expm1(1e-10))
    assert call("reciprocal_gap", large) == pytest.approx(1.0 / large - 1.0 / (large + 1.0))
    assert call("cos_diff", 1.0, 1.0 + 1e-8) == pytest.approx(np.cos(1.0) - np.cos(1.0 + 1e-8))

    scores = np.array([1000.0, 1001.0, 999.0])
    assert call("log_sum_exp", scores) == pytest.approx(
        1001.0 + np.log(1.0 + np.exp(-1.0) + np.exp(-2.0))
    )
    terms = np.full(10_000, 0.1)
    assert call("kahan_sum", terms) == 1000.0

    primary, secondary = call("stable_quadratic_roots", 1.0, 1e8, 1.0)
    assert primary * secondary == pytest.approx(1.0)
    assert primary + secondary == pytest.approx(-1e8)

    nodes, weights = call("golub_welsch_legendre", 5)
    assert np.sum(weights) == pytest.approx(2.0)
    assert np.sum(weights * nodes**2) == pytest.approx(2.0 / 3.0)

    blocks = [np.array([[2.0, 0.0], [0.0, 3.0]]), np.eye(2), np.eye(2), np.eye(2) * 4.0]
    blocked = np.block([[blocks[0], blocks[1]], [blocks[2], blocks[3]]])
    assert call("schur_complement_inverse", *blocks) == pytest.approx(np.linalg.inv(blocked))
    base = np.eye(3) * 2.0
    update_u = np.array([[1.0], [0.0], [0.0]])
    core = np.array([[1.0]])
    update_v = np.array([[0.0, 1.0, 0.0]])
    expected = np.linalg.inv(base + update_u @ core @ update_v)
    assert call("woodbury_inverse", np.linalg.inv(base), update_u, core, update_v) == pytest.approx(
        expected
    )


def test_welford_matches_sample_variance() -> None:
    """The one-pass accumulator matches the unbiased sample variance."""
    sample = np.array([1.0, 2.0, 4.0, 8.0])
    mean, variance, count = call("welford_stats", sample)
    assert count == 4
    assert mean == pytest.approx(sample.mean())
    assert variance == pytest.approx(sample.var(ddof=1))


def test_sympy_number_theory_matches_exact_values() -> None:
    """SymPy number-theory entries match known integers and fractions."""
    import sympy as sp

    assert call("factorial", 5) == 120
    assert call("gcd", 240, 46) == 2
    assert call("lcm", 6, 8) == 24
    divisor, coeff_s, coeff_t = call("extended_gcd", 240, 46)
    assert divisor == 2
    assert coeff_s * 240 + coeff_t * 46 == divisor
    assert call("binomial", 5, 2) == 10
    assert call("fibonacci", 10) == 55
    assert call("euler_totient", 10) == 4
    assert call("chinese_remainder", [2, 3, 2], [3, 5, 7]) == (23, 105)
    assert call("integer_square_root", 10) == 3
    assert call("is_prime", 97) is True
    assert call("is_prime", 1) is False
    assert call("prime_sieve", 10) == [2, 3, 5, 7]
    assert call("continued_fraction", 13, 17)[0] == 0
    assert call("modular_power", 2, 10, 1000) == 24
    assert call("catalan_number", 5) == 42
    assert call("mobius", 30) == -1
    assert call("factor_integer", 84) == {2: 2, 3: 1, 7: 1}
    assert call("rational_number", "0.25") == (1, 4)
    assert call("arithmetic_series_sum", 1, 2, 4) == 16
    ratio_sum = sp.Rational(1) + sp.Rational(1, 2) + sp.Rational(1, 4)
    assert call("geometric_series_sum", 1, 1, 2, 3) == (
        int(ratio_sum.numerator),
        int(ratio_sum.denominator),
    )
    numer, denom = call("harmonic_number", 5)
    assert sp.Rational(numer, denom) == sp.Rational(137, 60)
    with pytest.raises(AlgorithmInputError):
        call("chinese_remainder", [1, 2], [2, 4])


def test_sympy_calculus_identities() -> None:
    """Symbolic calculus entries reproduce the closed forms."""
    import sympy as sp

    x_symbol, y_symbol = sp.symbols("x y")
    assert call("binomial_expansion", 3) == sp.expand((x_symbol + y_symbol) ** 3)
    assert call("maclaurin_exponential", 4) == 1 + x_symbol + x_symbol**2 / 2 + x_symbol**3 / 6
    assert call("gaussian_integral") == sp.sqrt(sp.pi)
    frequency = sp.symbols("s", positive=True)
    assert sp.simplify(call("laplace_exponential", 3) - 1 / (frequency + 3)) == 0
    assert call("gamma_function", 5) == 24
    roots = call("exact_quadratic_roots", 1, -3, 2)
    assert set(roots) == {1, 2}


def test_pyarrow_reductions_and_distances() -> None:
    """PyArrow compute entries match NumPy on a finite sample."""
    pytest.importorskip("pyarrow")
    sample = np.array([1.0, 2.0, 4.0, 7.0])
    assert call("arrow_sum", sample) == pytest.approx(14.0)
    assert call("arrow_mean", sample) == pytest.approx(3.5)
    assert call("arrow_min", sample) == pytest.approx(1.0)
    assert call("arrow_max", sample) == pytest.approx(7.0)
    assert call("arrow_median", sample) == pytest.approx(3.0)
    assert call("arrow_abs", np.array([-1.5, 2.0])) == pytest.approx(np.array([1.5, 2.0]))
    assert call("arrow_floor", np.array([1.2, -1.2])) == pytest.approx(np.array([1.0, -2.0]))
    assert call("arrow_ceil", np.array([1.2, -1.2])) == pytest.approx(np.array([2.0, -1.0]))
    assert call("arrow_sign", np.array([-2.0, 0.0, 3.0])) == pytest.approx(
        np.array([-1.0, 0.0, 1.0])
    )
    assert call("arrow_geometric_mean", np.array([1.0, 4.0])) == pytest.approx(2.0)
    assert call("arrow_mean_absolute_deviation", sample) == pytest.approx(
        np.mean(np.abs(sample - sample.mean()))
    )
    assert call("arrow_weighted_mean", np.array([1.0, 3.0]), np.array([1.0, 3.0])) == pytest.approx(
        2.5
    )
    left = np.array([1.0, 2.0])
    right = np.array([4.0, 6.0])
    assert call("arrow_chebyshev_distance", left, right) == pytest.approx(4.0)
    assert call("arrow_manhattan_distance", left, right) == pytest.approx(7.0)
    assert call("arrow_euclidean_distance", left, right) == pytest.approx(5.0)


def test_arrow_dependency_error_when_missing() -> None:
    """Calling an Arrow kernel without pyarrow names the missing extra."""
    try:
        import pyarrow  # noqa: F401
    except ImportError:
        with pytest.raises(AlgorithmDependencyError):
            call("arrow_masked_l2_norm", object(), "value")
        return
    pytest.skip("pyarrow is installed")
