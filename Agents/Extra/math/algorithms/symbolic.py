"""Symbolic number-theoretic and algebraic helpers backed by sympy."""

from __future__ import annotations

import re

import sympy
from sympy.ntheory.continued_fraction import continued_fraction as _continued_fraction
from sympy.ntheory.modular import solve_congruence

from algorithms.errors import AlgorithmInputError

__all__ = [
    "factorial",
    "gcd",
    "lcm",
    "extended_gcd",
    "binomial",
    "fibonacci",
    "euler_totient",
    "chinese_remainder",
    "integer_square_root",
    "is_prime",
    "prime_sieve",
    "continued_fraction",
    "binomial_expansion",
    "maclaurin_exponential",
    "gaussian_integral",
    "laplace_exponential",
    "gamma_function",
    "exact_quadratic_roots",
    "arithmetic_series_sum",
    "geometric_series_sum",
    "harmonic_number",
    "catalan_number",
    "mobius",
    "factor_integer",
    "rational_number",
    "modular_power",
    "upstream",
]

_RATIONAL_RE = re.compile(r"[+-]?(0|[1-9]\d*)(\.\d+)?")


def _reject_bool(*values: object) -> None:
    """Raise AlgorithmInputError if any value is a bool."""
    if any(isinstance(value, bool) for value in values):
        raise AlgorithmInputError("bool values are not allowed")


def factorial(n: int) -> int:
    """Return n! as a Python int."""
    _reject_bool(n)
    if n < 0:
        raise AlgorithmInputError("n must be non-negative")
    return int(sympy.factorial(n))


def gcd(left: int, right: int) -> int:
    """Return the greatest common divisor of two integers."""
    _reject_bool(left, right)
    return int(sympy.gcd(left, right))


def lcm(left: int, right: int) -> int:
    """Return the least common multiple of two integers."""
    _reject_bool(left, right)
    return int(sympy.lcm(left, right))


def extended_gcd(left: int, right: int) -> tuple[int, int, int]:
    """Return (g, s, t) so that g = s*left + t*right and g >= 0."""
    _reject_bool(left, right)
    # gcdex returns (s, t, g) with g = s*left + t*right. igcdex is not in sympy.
    s, t, g = sympy.gcdex(left, right)
    if g < 0:
        g, s, t = -g, -s, -t
    return int(g), int(s), int(t)


def binomial(n: int, k: int) -> int:
    """Return the binomial coefficient C(n, k)."""
    _reject_bool(n, k)
    return int(sympy.binomial(n, k))


def fibonacci(n: int) -> int:
    """Return the n-th Fibonacci number with F(0) = 0."""
    _reject_bool(n)
    if n < 0:
        raise AlgorithmInputError("n must be non-negative")
    return int(sympy.fibonacci(n))


def euler_totient(n: int) -> int:
    """Return Euler's totient phi(n) for n >= 1."""
    _reject_bool(n)
    if n < 1:
        raise AlgorithmInputError("n must be positive")
    return int(sympy.totient(n))


def chinese_remainder(remainders: list[int], moduli: list[int]) -> tuple[int, int]:
    """Solve a system of congruences and return (solution, combined_modulus)."""
    if not remainders or not moduli:
        raise AlgorithmInputError("remainders and moduli must be non-empty")
    if len(remainders) != len(moduli):
        raise AlgorithmInputError("remainders and moduli must have the same length")
    _reject_bool(*remainders, *moduli)
    if any(modulus <= 0 for modulus in moduli):
        raise AlgorithmInputError("moduli must be positive")
    result = solve_congruence(*zip(remainders, moduli))
    if result is None:
        raise AlgorithmInputError("no solution exists for the given congruences")
    x, modulus = result
    return int(x), int(modulus)


def integer_square_root(n: int) -> int:
    """Return the largest integer whose square is less than or equal to n."""
    _reject_bool(n)
    if n < 0:
        raise AlgorithmInputError("n must be non-negative")
    root, _ = sympy.integer_nthroot(n, 2)
    return int(root)


def is_prime(n: int) -> bool:
    """Return True if n is a prime number."""
    _reject_bool(n)
    if n < 2:
        return False
    return bool(sympy.isprime(n))


def prime_sieve(limit: int) -> list[int]:
    """Return a list of all prime numbers less than or equal to limit."""
    _reject_bool(limit)
    if limit < 0:
        raise AlgorithmInputError("limit must be non-negative")
    return [int(prime) for prime in sympy.primerange(2, limit + 1)]


def continued_fraction(numerator: int, denominator: int) -> list[int]:
    """Return the simple continued fraction expansion of a rational number."""
    _reject_bool(numerator, denominator)
    if denominator == 0:
        raise AlgorithmInputError("denominator must not be zero")
    return [int(term) for term in _continued_fraction(sympy.Rational(numerator, denominator))]


def binomial_expansion(power: int) -> sympy.Expr:
    """Return the expanded form of (x + y)**power."""
    _reject_bool(power)
    if power < 0:
        raise AlgorithmInputError("power must be non-negative")
    x, y = sympy.symbols("x y")
    return sympy.expand((x + y) ** power)


def maclaurin_exponential(order: int) -> sympy.Expr:
    """Return the Maclaurin series of exp(x) truncated to the given order."""
    _reject_bool(order)
    if order < 0:
        raise AlgorithmInputError("order must be non-negative")
    x = sympy.symbols("x")
    if order == 0:
        return sympy.Integer(0)
    return sympy.series(sympy.exp(x), x, 0, order).removeO()


def gaussian_integral() -> sympy.Expr:
    """Return the exact value of the Gaussian integral over the real line."""
    return sympy.sqrt(sympy.pi)


def laplace_exponential(rate: int) -> sympy.Expr:
    """Return the Laplace transform of exp(-rate*t)."""
    _reject_bool(rate)
    if rate <= 0:
        raise AlgorithmInputError("rate must be positive")
    t = sympy.symbols("t", positive=True)
    s = sympy.symbols("s", positive=True)
    expr = sympy.exp(-rate * t)
    result = sympy.laplace_transform(expr, t, s, noconds=True)
    return sympy.simplify(result)


def gamma_function(n: int) -> int:
    """Return Gamma(n) for a positive integer n."""
    _reject_bool(n)
    if n < 1:
        raise AlgorithmInputError("n must be positive")
    return int(sympy.gamma(n))


def exact_quadratic_roots(a: int, b: int, c: int) -> tuple[sympy.Expr, sympy.Expr]:
    """Return the exact roots of a*x**2 + b*x + c, duplicating a double root."""
    _reject_bool(a, b, c)
    if a == 0:
        raise AlgorithmInputError("a must not be zero")
    discriminant = b * b - 4 * a * c
    sqrt_disc = sympy.sqrt(discriminant)
    denom = 2 * a
    root1 = (-b + sqrt_disc) / denom
    root2 = (-b - sqrt_disc) / denom
    if discriminant == 0:
        return root1, root1
    return root1, root2


def arithmetic_series_sum(first: int, difference: int, count: int) -> int:
    """Return the sum of the first count terms of an arithmetic progression."""
    _reject_bool(first, difference, count)
    if count < 0:
        raise AlgorithmInputError("count must be non-negative")
    if count == 0:
        return 0
    return count * (2 * first + (count - 1) * difference) // 2


def geometric_series_sum(
    first: int,
    ratio_numerator: int,
    ratio_denominator: int,
    count: int,
) -> tuple[int, int]:
    """Return the reduced numerator and denominator of a finite geometric sum."""
    _reject_bool(first, ratio_numerator, ratio_denominator, count)
    if count < 0:
        raise AlgorithmInputError("count must be non-negative")
    if ratio_denominator == 0:
        raise AlgorithmInputError("ratio_denominator must not be zero")
    if count == 0:
        return 0, 1
    ratio = sympy.Rational(ratio_numerator, ratio_denominator)
    if ratio == 1:
        return first * count, 1
    total = sympy.Rational(first, 1) * (1 - ratio**count) / (1 - ratio)
    num, den = sympy.simplify(total).as_numer_denom()
    return int(num), int(den)


def harmonic_number(n: int) -> tuple[int, int]:
    """Return the n-th harmonic number as a reduced (numerator, denominator)."""
    _reject_bool(n)
    if n < 1:
        raise AlgorithmInputError("n must be positive")
    h = sympy.harmonic(n)
    num, den = h.as_numer_denom()
    return int(num), int(den)


def catalan_number(n: int) -> int:
    """Return the n-th Catalan number."""
    _reject_bool(n)
    if n < 0:
        raise AlgorithmInputError("n must be non-negative")
    return int(sympy.catalan(n))


def mobius(n: int) -> int:
    """Return the Möbius function value for n >= 1."""
    _reject_bool(n)
    if n < 1:
        raise AlgorithmInputError("n must be positive")
    return int(sympy.mobius(n))


def factor_integer(n: int) -> dict[int, int]:
    """Return the prime factorisation of n as a mapping prime -> exponent."""
    _reject_bool(n)
    if n <= 1:
        raise AlgorithmInputError("n must be greater than 1")
    factors = sympy.factorint(n)
    return {int(prime): int(exponent) for prime, exponent in factors.items()}


def rational_number(literal: str) -> tuple[int, int]:
    """Parse a decimal literal into a reduced numerator and denominator."""
    _reject_bool(literal)
    if not isinstance(literal, str):
        raise AlgorithmInputError("literal must be a string")
    if _RATIONAL_RE.fullmatch(literal) is None:
        raise AlgorithmInputError("literal does not match a valid decimal number")
    value = sympy.Rational(literal)
    return int(value.numerator), int(value.denominator)


def modular_power(base: int, exponent: int, modulus: int) -> int:
    """Return (base**exponent) mod modulus using binary exponentiation."""
    _reject_bool(base, exponent, modulus)
    if exponent < 0:
        raise AlgorithmInputError("exponent must be non-negative")
    if modulus <= 0:
        raise AlgorithmInputError("modulus must be positive")
    return pow(base, exponent, modulus)


def upstream(path: str) -> str:
    """Return the upstream TheAlgorithms URL for the given repository path."""
    _reject_bool(path)
    if not isinstance(path, str):
        raise AlgorithmInputError("path must be a string")
    return f"https://github.com/TheAlgorithms/Python/blob/master/{path}"
