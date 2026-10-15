"""Shared pytest hooks for the TechNews suite."""

from __future__ import annotations

import importlib.util

import pytest

# The forecast engine is the shared `Prediction` module; each product (TechNews, BotDeal, ...)
# brings its own features, scoring and evaluation around it. Tests marked `engine` need it.
_ENGINE_MISSING = importlib.util.find_spec("Prediction") is None
_SKIP_REASON = (
    "Prediction engine not importable (shared module; put the Prediction package on the path)"
)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip engine-backed tests, with a stated reason, when the shared engine is absent."""
    if not _ENGINE_MISSING:
        return
    skip = pytest.mark.skip(reason=_SKIP_REASON)
    for item in items:
        if "engine" in item.keywords:
            item.add_marker(skip)
