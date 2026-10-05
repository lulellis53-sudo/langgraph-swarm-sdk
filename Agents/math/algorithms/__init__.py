"""Python algorithm database for the math agent.

The kernels implement the seven pillars in ``Agents/math/AGENTS.md``. Import this
package by placing ``Agents/math`` on ``sys.path``:

    from algorithms import by_pillar, catalog, get

There is no ``Agents/math/__init__.py``. The standard-library ``math`` module
stays the builtin, and this folder is not a ``math`` package.
"""

from algorithms.catalog import by_pillar, call, catalog, get, search
from algorithms.errors import (
    AlgorithmDependencyError,
    AlgorithmError,
    AlgorithmInputError,
    AlgorithmNotFoundError,
    NotPositiveDefiniteError,
)
from algorithms.record import Algorithm, Pillar, Precision

__all__ = [
    "Algorithm",
    "AlgorithmDependencyError",
    "AlgorithmError",
    "AlgorithmInputError",
    "AlgorithmNotFoundError",
    "NotPositiveDefiniteError",
    "Pillar",
    "Precision",
    "by_pillar",
    "call",
    "catalog",
    "get",
    "search",
]
