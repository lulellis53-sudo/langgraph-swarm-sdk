"""WebSearch pipeline: frontend searchers → midend crawl/scrape → backend extract."""

from __future__ import annotations

from typing import Any

from WebSearch.int_ import __all__ as __all__
from WebSearch.int_ import run_pipeline as run_pipeline


def __getattr__(name: str) -> Any:
    """Forward public names to ``WebSearch.int_`` (lazy load on first access)."""
    from WebSearch import int_ as impl

    return getattr(impl, name)


def __dir__() -> list[str]:
    """Return sorted public names for ``dir(WebSearch)``."""
    return sorted(__all__)
