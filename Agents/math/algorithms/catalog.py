"""Registry of the math-agent algorithms."""

from collections.abc import Mapping
from types import MappingProxyType

from algorithms.arrow_compute import (
    arrow_abs,
    arrow_ceil,
    arrow_chebyshev_distance,
    arrow_euclidean_distance,
    arrow_floor,
    arrow_geometric_mean,
    arrow_manhattan_distance,
    arrow_max,
    arrow_mean,
    arrow_mean_absolute_deviation,
    arrow_median,
    arrow_min,
    arrow_sign,
    arrow_sum,
    arrow_weighted_mean,
)
from algorithms.columnar import (
    arrow_masked_l2_norm,
    arrow_to_numpy_zerocopy,
    stream_arrow_ipc_mips,
    stream_arrow_welford_stats,
    welford_stats,
)
from algorithms.compute import (
    attainable_performance,
    cooley_tukey_fft,
    strassen_matmul,
    tiled_matmul,
)
from algorithms.equations import damped_newton_root, verify_bm25_asymptotics
from algorithms.errors import AlgorithmError, AlgorithmInputError, AlgorithmNotFoundError
from algorithms.formula import (
    cos_diff,
    expm1_stable,
    golub_welsch_legendre,
    kahan_sum,
    log1p_stable,
    log_sum_exp,
    one_minus_cos,
    reciprocal_gap,
    schur_complement_inverse,
    sqrt_diff_stable,
    stable_quadratic_roots,
    woodbury_inverse,
)
from algorithms.matrix import (
    cholesky_factorization,
    condition_number_2,
    householder_qr,
    spmv_csr,
)
from algorithms.record import Algorithm, Pillar, Precision
from algorithms.symbolic import (
    arithmetic_series_sum,
    binomial,
    binomial_expansion,
    catalan_number,
    chinese_remainder,
    continued_fraction,
    euler_totient,
    exact_quadratic_roots,
    extended_gcd,
    factor_integer,
    factorial,
    fibonacci,
    gamma_function,
    gaussian_integral,
    gcd,
    geometric_series_sum,
    harmonic_number,
    integer_square_root,
    is_prime,
    laplace_exponential,
    lcm,
    maclaurin_exponential,
    mobius,
    modular_power,
    prime_sieve,
    rational_number,
    upstream,
)
from algorithms.vector import (
    cosine_similarity,
    euclidean_distance,
    hamming_angular_cosine,
    hnsw_greedy_search,
    mips_lift,
    sq8_encode_decode,
    train_ivf_pq_codebooks,
)
from algorithms.verify import verify_numerical_solution
from algorithms.vision import (
    compute_homography_dlt,
    fundamental_matrix_8point,
    pinhole_project,
    sobel_gradients_2d,
)

__all__ = ["by_pillar", "call", "catalog", "get", "search"]


def _algorithm(
    function: object,
    *,
    pillar: Pillar,
    summary: str,
    time: str,
    space: str,
    precision: Precision,
    source: str = "",
) -> Algorithm:
    if not callable(function):
        raise AlgorithmError("catalog entry is not callable")
    return Algorithm(
        id=function.__name__,
        pillar=pillar,
        summary=summary,
        complexity_time=time,
        complexity_space=space,
        precision=precision,
        function=function,
        source=source,
    )


def _from_the_algorithms(
    function: object,
    *,
    pillar: Pillar,
    summary: str,
    time: str,
    space: str,
    precision: Precision,
    path: str,
) -> Algorithm:
    return _algorithm(
        function,
        pillar=pillar,
        summary=summary,
        time=time,
        space=space,
        precision=precision,
        source=upstream(path),
    )


def _the_algorithms() -> tuple[Algorithm, ...]:
    """Register exact SymPy algorithms and PyArrow compute algorithms."""
    exact = Precision.EXACT
    double = Precision.DOUBLE
    formula = Pillar.FORMULA
    equation = Pillar.EQUATION
    columnar = Pillar.COLUMNAR
    return (
        _from_the_algorithms(
            factorial,
            pillar=formula,
            summary="Factorial of a non-negative integer.",
            time="O(n)",
            space="O(1)",
            precision=exact,
            path="maths/factorial.py",
        ),
        _from_the_algorithms(
            gcd,
            pillar=formula,
            summary="Greatest common divisor.",
            time="O(log n)",
            space="O(1)",
            precision=exact,
            path="maths/greatest_common_divisor.py",
        ),
        _from_the_algorithms(
            lcm,
            pillar=formula,
            summary="Least common multiple.",
            time="O(log n)",
            space="O(1)",
            precision=exact,
            path="maths/least_common_multiple.py",
        ),
        _from_the_algorithms(
            extended_gcd,
            pillar=formula,
            summary="Extended Euclidean algorithm.",
            time="O(log n)",
            space="O(1)",
            precision=exact,
            path="maths/extended_euclidean_algorithm.py",
        ),
        _from_the_algorithms(
            binomial,
            pillar=formula,
            summary="Binomial coefficient.",
            time="O(k)",
            space="O(1)",
            precision=exact,
            path="maths/binomial_coefficient.py",
        ),
        _from_the_algorithms(
            fibonacci,
            pillar=formula,
            summary="Fibonacci number.",
            time="O(n)",
            space="O(1)",
            precision=exact,
            path="maths/fibonacci.py",
        ),
        _from_the_algorithms(
            euler_totient,
            pillar=formula,
            summary="Euler totient.",
            time="O(sqrt n)",
            space="O(1)",
            precision=exact,
            path="maths/eulers_totient.py",
        ),
        _from_the_algorithms(
            chinese_remainder,
            pillar=formula,
            summary="Chinese remainder theorem.",
            time="O(k log n)",
            space="O(k)",
            precision=exact,
            path="maths/chinese_remainder_theorem.py",
        ),
        _from_the_algorithms(
            integer_square_root,
            pillar=formula,
            summary="Integer square root.",
            time="O(log n)",
            space="O(1)",
            precision=exact,
            path="maths/integer_square_root.py",
        ),
        _from_the_algorithms(
            is_prime,
            pillar=formula,
            summary="Primality test.",
            time="O(sqrt n)",
            space="O(1)",
            precision=exact,
            path="maths/prime_check.py",
        ),
        _from_the_algorithms(
            prime_sieve,
            pillar=formula,
            summary="Primes up to a limit.",
            time="O(n log log n)",
            space="O(n)",
            precision=exact,
            path="maths/sieve_of_eratosthenes.py",
        ),
        _from_the_algorithms(
            continued_fraction,
            pillar=formula,
            summary="Continued fraction of a rational.",
            time="O(log n)",
            space="O(log n)",
            precision=exact,
            path="maths/continued_fraction.py",
        ),
        _from_the_algorithms(
            binomial_expansion,
            pillar=equation,
            summary="Binomial expansion of (x + y)^n.",
            time="O(n)",
            space="O(n)",
            precision=exact,
            path="maths/binomial_expansion.py",
        ),
        _from_the_algorithms(
            maclaurin_exponential,
            pillar=equation,
            summary="Maclaurin polynomial of exp(x).",
            time="O(n)",
            space="O(n)",
            precision=exact,
            path="maths/maclaurin_series.py",
        ),
        _from_the_algorithms(
            gaussian_integral,
            pillar=equation,
            summary="Exact Gaussian integral of exp(-x^2).",
            time="O(1)",
            space="O(1)",
            precision=exact,
            path="maths/gaussian.py",
        ),
        _from_the_algorithms(
            laplace_exponential,
            pillar=equation,
            summary="Laplace transform of an exponential decay.",
            time="O(1)",
            space="O(1)",
            precision=exact,
            path="maths/laplace_transformation.py",
        ),
        _from_the_algorithms(
            gamma_function,
            pillar=equation,
            summary="Gamma value at a positive integer.",
            time="O(n)",
            space="O(1)",
            precision=exact,
            path="maths/gamma.py",
        ),
        _from_the_algorithms(
            exact_quadratic_roots,
            pillar=equation,
            summary="Exact quadratic roots.",
            time="O(1)",
            space="O(1)",
            precision=exact,
            path="maths/quadratic_equations_complex_numbers.py",
        ),
        _from_the_algorithms(
            arithmetic_series_sum,
            pillar=formula,
            summary="Sum of a finite arithmetic series.",
            time="O(1)",
            space="O(1)",
            precision=exact,
            path="maths/sum_of_arithmetic_series.py",
        ),
        _from_the_algorithms(
            geometric_series_sum,
            pillar=formula,
            summary="Exact sum of a finite geometric series.",
            time="O(n)",
            space="O(1)",
            precision=exact,
            path="maths/sum_of_geometric_progression.py",
        ),
        _from_the_algorithms(
            harmonic_number,
            pillar=formula,
            summary="Harmonic number as a reduced fraction.",
            time="O(n)",
            space="O(1)",
            precision=exact,
            path="maths/sum_of_harmonic_series.py",
        ),
        _from_the_algorithms(
            catalan_number,
            pillar=formula,
            summary="Catalan number.",
            time="O(n)",
            space="O(1)",
            precision=exact,
            path="maths/special_numbers/catalan_number.py",
        ),
        _from_the_algorithms(
            mobius,
            pillar=formula,
            summary="Mobius function.",
            time="O(sqrt n)",
            space="O(1)",
            precision=exact,
            path="maths/mobius_function.py",
        ),
        _from_the_algorithms(
            factor_integer,
            pillar=formula,
            summary="Prime factorization.",
            time="O(sqrt n)",
            space="O(log n)",
            precision=exact,
            path="maths/prime_factors.py",
        ),
        _from_the_algorithms(
            rational_number,
            pillar=formula,
            summary="Decimal literal to a reduced fraction.",
            time="O(digits)",
            space="O(digits)",
            precision=exact,
            path="maths/decimal_to_fraction.py",
        ),
        _from_the_algorithms(
            modular_power,
            pillar=formula,
            summary="Binary modular exponentiation.",
            time="O(log exponent)",
            space="O(1)",
            precision=exact,
            path="maths/modular_exponential.py",
        ),
        _from_the_algorithms(
            arrow_sum,
            pillar=columnar,
            summary="PyArrow sum.",
            time="O(n)",
            space="O(n)",
            precision=double,
            path="maths/basic_maths.py",
        ),
        _from_the_algorithms(
            arrow_mean,
            pillar=columnar,
            summary="PyArrow arithmetic mean.",
            time="O(n)",
            space="O(n)",
            precision=double,
            path="maths/average_mean.py",
        ),
        _from_the_algorithms(
            arrow_min,
            pillar=columnar,
            summary="PyArrow minimum.",
            time="O(n)",
            space="O(n)",
            precision=double,
            path="maths/find_min.py",
        ),
        _from_the_algorithms(
            arrow_max,
            pillar=columnar,
            summary="PyArrow maximum.",
            time="O(n)",
            space="O(n)",
            precision=double,
            path="maths/find_max.py",
        ),
        _from_the_algorithms(
            arrow_abs,
            pillar=columnar,
            summary="PyArrow absolute value.",
            time="O(n)",
            space="O(n)",
            precision=double,
            path="maths/abs.py",
        ),
        _from_the_algorithms(
            arrow_floor,
            pillar=columnar,
            summary="PyArrow floor.",
            time="O(n)",
            space="O(n)",
            precision=double,
            path="maths/floor.py",
        ),
        _from_the_algorithms(
            arrow_ceil,
            pillar=columnar,
            summary="PyArrow ceiling.",
            time="O(n)",
            space="O(n)",
            precision=double,
            path="maths/ceil.py",
        ),
        _from_the_algorithms(
            arrow_sign,
            pillar=columnar,
            summary="PyArrow sign.",
            time="O(n)",
            space="O(n)",
            precision=double,
            path="maths/signum.py",
        ),
        _from_the_algorithms(
            arrow_median,
            pillar=columnar,
            summary="PyArrow median quantile.",
            time="O(n log n)",
            space="O(n)",
            precision=double,
            path="maths/average_median.py",
        ),
        _from_the_algorithms(
            arrow_geometric_mean,
            pillar=columnar,
            summary="PyArrow geometric mean.",
            time="O(n)",
            space="O(n)",
            precision=double,
            path="maths/geometric_mean.py",
        ),
        _from_the_algorithms(
            arrow_mean_absolute_deviation,
            pillar=columnar,
            summary="PyArrow mean absolute deviation.",
            time="O(n)",
            space="O(n)",
            precision=double,
            path="maths/average_absolute_deviation.py",
        ),
        _from_the_algorithms(
            arrow_weighted_mean,
            pillar=columnar,
            summary="PyArrow weighted mean.",
            time="O(n)",
            space="O(n)",
            precision=double,
            path="maths/weighted_average.py",
        ),
        _from_the_algorithms(
            arrow_chebyshev_distance,
            pillar=columnar,
            summary="PyArrow Chebyshev distance.",
            time="O(d)",
            space="O(d)",
            precision=double,
            path="maths/chebyshev_distance.py",
        ),
        _from_the_algorithms(
            arrow_manhattan_distance,
            pillar=columnar,
            summary="PyArrow Manhattan distance.",
            time="O(d)",
            space="O(d)",
            precision=double,
            path="maths/manhattan_distance.py",
        ),
        _from_the_algorithms(
            arrow_euclidean_distance,
            pillar=columnar,
            summary="PyArrow Euclidean distance.",
            time="O(d)",
            space="O(d)",
            precision=double,
            path="maths/euclidean_distance.py",
        ),
    )


def _build() -> tuple[Algorithm, ...]:
    entries = (
        _algorithm(
            euclidean_distance,
            pillar=Pillar.VECTORDB,
            summary="Euclidean distance between two vectors.",
            time="O(d)",
            space="O(1)",
            precision=Precision.DOUBLE,
        ),
        _algorithm(
            cosine_similarity,
            pillar=Pillar.VECTORDB,
            summary="Cosine similarity of two non-zero vectors.",
            time="O(d)",
            space="O(1)",
            precision=Precision.DOUBLE,
        ),
        _algorithm(
            mips_lift,
            pillar=Pillar.VECTORDB,
            summary="Lift inner-product search to Euclidean search.",
            time="O(nd)",
            space="O(nd)",
            precision=Precision.DOUBLE,
        ),
        _algorithm(
            hamming_angular_cosine,
            pillar=Pillar.VECTORDB,
            summary="Angular cosine from the Hamming distance of two codes.",
            time="O(d)",
            space="O(1)",
            precision=Precision.DOUBLE,
        ),
        _algorithm(
            sq8_encode_decode,
            pillar=Pillar.VECTORDB,
            summary="Uniform 8-bit scalar quantization and reconstruction.",
            time="O(n)",
            space="O(n)",
            precision=Precision.HALF,
        ),
        _algorithm(
            hnsw_greedy_search,
            pillar=Pillar.VECTORDB,
            summary="Greedy beam search on one HNSW layer.",
            time="O(ef * degree)",
            space="O(ef)",
            precision=Precision.DOUBLE,
        ),
        _algorithm(
            train_ivf_pq_codebooks,
            pillar=Pillar.VECTORDB,
            summary="Lloyd codebooks for product quantization.",
            time="O(iterations * n * k * d)",
            space="O(m * k * d / m)",
            precision=Precision.SINGLE,
        ),
        _algorithm(
            attainable_performance,
            pillar=Pillar.PERFORMANCE,
            summary="Roofline attainable rate from intensity and bandwidth.",
            time="O(1)",
            space="O(1)",
            precision=Precision.DOUBLE,
        ),
        _algorithm(
            tiled_matmul,
            pillar=Pillar.PERFORMANCE,
            summary="Cache-blocked matrix product.",
            time="O(mkn)",
            space="O(mn)",
            precision=Precision.DOUBLE,
        ),
        _algorithm(
            cooley_tukey_fft,
            pillar=Pillar.PERFORMANCE,
            summary="Radix-2 Cooley-Tukey Fourier transform.",
            time="O(n log n)",
            space="O(n log n)",
            precision=Precision.DOUBLE,
        ),
        _algorithm(
            strassen_matmul,
            pillar=Pillar.PERFORMANCE,
            summary="Strassen matrix product on a power-of-two pad.",
            time="O(n^log2(7))",
            space="O(n^2)",
            precision=Precision.DOUBLE,
        ),
        _algorithm(
            damped_newton_root,
            pillar=Pillar.EQUATION,
            summary="Levenberg-Marquardt damped Newton root.",
            time="O(iterations * n^3)",
            space="O(n^2)",
            precision=Precision.DOUBLE,
        ),
        _algorithm(
            verify_bm25_asymptotics,
            pillar=Pillar.EQUATION,
            summary="Symbolic proof of BM25 monotonicity and saturation.",
            time="O(1)",
            space="O(1)",
            precision=Precision.EXACT,
        ),
        _algorithm(
            pinhole_project,
            pillar=Pillar.VISION,
            summary="Pinhole projection x = K [R | t] X.",
            time="O(n)",
            space="O(n)",
            precision=Precision.DOUBLE,
        ),
        _algorithm(
            compute_homography_dlt,
            pillar=Pillar.VISION,
            summary="Planar homography from the direct linear transform.",
            time="O(n)",
            space="O(n)",
            precision=Precision.DOUBLE,
        ),
        _algorithm(
            fundamental_matrix_8point,
            pillar=Pillar.VISION,
            summary="Rank-2 fundamental matrix from normalized correspondences.",
            time="O(n)",
            space="O(n)",
            precision=Precision.DOUBLE,
        ),
        _algorithm(
            sobel_gradients_2d,
            pillar=Pillar.VISION,
            summary="Sobel image gradients and their magnitude.",
            time="O(hw)",
            space="O(hw)",
            precision=Precision.DOUBLE,
        ),
        _algorithm(
            householder_qr,
            pillar=Pillar.MATRIX,
            summary="Householder QR factorization.",
            time="O(mn^2)",
            space="O(m^2)",
            precision=Precision.DOUBLE,
        ),
        _algorithm(
            cholesky_factorization,
            pillar=Pillar.MATRIX,
            summary="Lower Cholesky factor of a positive definite matrix.",
            time="O(n^3)",
            space="O(n^2)",
            precision=Precision.DOUBLE,
        ),
        _algorithm(
            spmv_csr,
            pillar=Pillar.MATRIX,
            summary="CSR sparse matrix-vector product.",
            time="O(nnz)",
            space="O(rows)",
            precision=Precision.DOUBLE,
        ),
        _algorithm(
            condition_number_2,
            pillar=Pillar.MATRIX,
            summary="2-norm condition number from singular values.",
            time="O(min(mn^2, m^2 n))",
            space="O(min(m, n))",
            precision=Precision.DOUBLE,
        ),
        _algorithm(
            verify_numerical_solution,
            pillar=Pillar.MATRIX,
            summary="Residual, backward error, and forward-error bound for Ax = b.",
            time="O(min(mn^2, m^2 n))",
            space="O(m)",
            precision=Precision.DOUBLE,
        ),
        _algorithm(
            arrow_to_numpy_zerocopy,
            pillar=Pillar.COLUMNAR,
            summary="Zero-copy NumPy view of one Arrow column.",
            time="O(1)",
            space="O(1)",
            precision=Precision.DOUBLE,
        ),
        _algorithm(
            arrow_masked_l2_norm,
            pillar=Pillar.COLUMNAR,
            summary="L2 norm of the valid values in an Arrow column.",
            time="O(n)",
            space="O(n)",
            precision=Precision.DOUBLE,
        ),
        _algorithm(
            stream_arrow_ipc_mips,
            pillar=Pillar.COLUMNAR,
            summary="Bounded-memory top-k inner-product scan of an Arrow IPC file.",
            time="O(rows * dim)",
            space="O(top_k)",
            precision=Precision.DOUBLE,
        ),
        _algorithm(
            stream_arrow_welford_stats,
            pillar=Pillar.COLUMNAR,
            summary="Streaming sample mean and variance over an Arrow IPC column.",
            time="O(n)",
            space="O(batch)",
            precision=Precision.DOUBLE,
        ),
        _algorithm(
            welford_stats,
            pillar=Pillar.COLUMNAR,
            summary="Sample mean and variance of a 1-D array.",
            time="O(n)",
            space="O(1)",
            precision=Precision.DOUBLE,
        ),
        _algorithm(
            golub_welsch_legendre,
            pillar=Pillar.FORMULA,
            summary="Gauss-Legendre nodes and weights via Golub-Welsch.",
            time="O(n^3)",
            space="O(n^2)",
            precision=Precision.DOUBLE,
        ),
        _algorithm(
            log_sum_exp,
            pillar=Pillar.FORMULA,
            summary="Stable log-sum-exp.",
            time="O(n)",
            space="O(n)",
            precision=Precision.DOUBLE,
        ),
        _algorithm(
            kahan_sum,
            pillar=Pillar.FORMULA,
            summary="Kahan compensated sum.",
            time="O(n)",
            space="O(1)",
            precision=Precision.DOUBLE,
        ),
        _algorithm(
            stable_quadratic_roots,
            pillar=Pillar.FORMULA,
            summary="Real quadratic roots shielded from cancellation.",
            time="O(1)",
            space="O(1)",
            precision=Precision.DOUBLE,
        ),
        _algorithm(
            sqrt_diff_stable,
            pillar=Pillar.FORMULA,
            summary="Stable evaluation of sqrt(x + 1) - sqrt(x).",
            time="O(1)",
            space="O(1)",
            precision=Precision.DOUBLE,
        ),
        _algorithm(
            one_minus_cos,
            pillar=Pillar.FORMULA,
            summary="Stable evaluation of 1 - cos(x).",
            time="O(1)",
            space="O(1)",
            precision=Precision.DOUBLE,
        ),
        _algorithm(
            log1p_stable,
            pillar=Pillar.FORMULA,
            summary="Stable evaluation of log(1 + x).",
            time="O(1)",
            space="O(1)",
            precision=Precision.DOUBLE,
        ),
        _algorithm(
            expm1_stable,
            pillar=Pillar.FORMULA,
            summary="Stable evaluation of exp(x) - 1.",
            time="O(1)",
            space="O(1)",
            precision=Precision.DOUBLE,
        ),
        _algorithm(
            reciprocal_gap,
            pillar=Pillar.FORMULA,
            summary="Stable evaluation of 1/x - 1/(x + 1).",
            time="O(1)",
            space="O(1)",
            precision=Precision.DOUBLE,
        ),
        _algorithm(
            cos_diff,
            pillar=Pillar.FORMULA,
            summary="Stable evaluation of cos(x) - cos(y).",
            time="O(1)",
            space="O(1)",
            precision=Precision.DOUBLE,
        ),
        _algorithm(
            schur_complement_inverse,
            pillar=Pillar.FORMULA,
            summary="Block inverse through the Schur complement.",
            time="O(n^3)",
            space="O(n^2)",
            precision=Precision.DOUBLE,
        ),
        _algorithm(
            woodbury_inverse,
            pillar=Pillar.FORMULA,
            summary="Rank-k update inverse through the Woodbury identity.",
            time="O(n^2 k + k^3)",
            space="O(n^2)",
            precision=Precision.DOUBLE,
        ),
    ) + _the_algorithms()
    found: dict[str, Algorithm] = {}
    for entry in entries:
        if entry.id in found:
            raise AlgorithmError(f"duplicate algorithm id: {entry.id}")
        found[entry.id] = entry
    return entries


_ORDERED = _build()
_BY_ID: Mapping[str, Algorithm] = MappingProxyType({item.id: item for item in _ORDERED})


def catalog() -> Mapping[str, Algorithm]:
    """Return the read-only algorithm catalog, keyed by id."""
    return _BY_ID


def get(algorithm_id: str) -> Algorithm:
    """Return one algorithm.

    Raises:
        AlgorithmNotFoundError: The id is not registered.
    """
    try:
        return _BY_ID[algorithm_id]
    except KeyError as err:
        raise AlgorithmNotFoundError(algorithm_id) from err


def by_pillar(pillar: Pillar | int) -> tuple[Algorithm, ...]:
    """Return algorithms that belong to one pillar, in catalog order.

    Raises:
        AlgorithmInputError: The pillar number is outside 1..7.
    """
    try:
        selected = pillar if isinstance(pillar, Pillar) else Pillar(int(pillar))
    except (TypeError, ValueError) as err:
        raise AlgorithmInputError(f"unknown pillar: {pillar}") from err
    return tuple(item for item in _ORDERED if item.pillar is selected)


def search(query: str) -> tuple[Algorithm, ...]:
    """Return algorithms whose id or summary contains the query."""
    needle = query.casefold().strip()
    if not needle:
        raise AlgorithmInputError("search query is empty")
    return tuple(
        item
        for item in _ORDERED
        if needle in item.id.casefold() or needle in item.summary.casefold()
    )


def call(algorithm_id: str, /, *args: object, **kwargs: object) -> object:
    """Look up an algorithm by id and call it."""
    return get(algorithm_id)(*args, **kwargs)
