"""Errors raised by the math algorithm database."""

from __future__ import annotations

__all__ = [
    "AlgorithmDependencyError",
    "AlgorithmError",
    "AlgorithmInputError",
    "AlgorithmNotFoundError",
    "NotPositiveDefiniteError",
]


class AlgorithmError(Exception):
    """Base error for the math algorithm database."""


class AlgorithmNotFoundError(AlgorithmError):
    """Raised when an algorithm id is absent from the catalog."""


class AlgorithmInputError(AlgorithmError, ValueError):
    """Raised when an algorithm receives an invalid argument."""


class AlgorithmDependencyError(AlgorithmError):
    """Raised when an optional numeric library is not installed."""


class NotPositiveDefiniteError(AlgorithmInputError):
    """Raised when a factorization requires a positive definite matrix."""
