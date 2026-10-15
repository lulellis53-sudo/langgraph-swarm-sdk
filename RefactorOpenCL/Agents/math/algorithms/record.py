"""Catalog record for one algorithm in the math database."""

from __future__ import annotations

import enum
from collections.abc import Callable
from dataclasses import dataclass

__all__ = ["Algorithm", "Pillar", "Precision"]


class Pillar(enum.IntEnum):
    """The seven pillars in ``Agents/math/AGENTS.md``."""

    VECTORDB = 1
    PERFORMANCE = 2
    EQUATION = 3
    VISION = 4
    MATRIX = 5
    COLUMNAR = 6
    FORMULA = 7


class Precision(enum.StrEnum):
    """Floating-point precision levels P0 through P4."""

    EXACT = "P0"
    ARBITRARY = "P1"
    DOUBLE = "P2"
    SINGLE = "P3"
    HALF = "P4"


@dataclass(frozen=True, slots=True)
class Algorithm:
    """One callable algorithm plus the metadata needed to select it.

    Args:
        id: Stable catalog key. It matches the function name.
        pillar: Contract pillar that owns the algorithm.
        summary: One-line description of what the callable does.
        complexity_time: Asymptotic time cost.
        complexity_space: Asymptotic extra memory.
        precision: Working precision of the implementation.
        function: Implementation. Arguments stay on the function itself.
        source: Upstream reference. Empty when the algorithm comes from the math contract.
    """

    id: str
    pillar: Pillar
    summary: str
    complexity_time: str
    complexity_space: str
    precision: Precision
    function: Callable[..., object]
    source: str = ""

    def __call__(self, *args: object, **kwargs: object) -> object:
        """Run the stored implementation."""
        return self.function(*args, **kwargs)
