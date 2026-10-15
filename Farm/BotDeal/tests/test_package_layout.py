"""Pins the merged package layout: new modules import, old packages are gone."""

from __future__ import annotations

import importlib

import pytest

REMOVED: list[str] = [
    "swarm_sdk.server",
    "swarm_sdk.execution",
    "swarm_sdk.observability",
    "swarm_sdk.prompting",
    "swarm_sdk.gpu",
    "swarm_sdk.math",
]
PRESENT: list[str] = [
    "swarm_sdk.serving.graphs",
    "swarm_sdk.runtime",
    "swarm_sdk.runtime.concurrency",
    "swarm_sdk.runtime.executor",
    "swarm_sdk.runtime.fanout",
    "swarm_sdk.runtime.metrics",
    "swarm_sdk.runtime.tracing",
    "swarm_sdk.runtime.usage",
    "swarm_sdk.models.budget",
    "swarm_sdk.compute",
    "swarm_sdk.compute.scoring",
    "swarm_sdk.compute.lazy_dispatcher",
    "swarm_sdk.compute.opencl_math",
    "swarm_sdk.compute.report",
]


@pytest.mark.parametrize("name", REMOVED)
def test_old_package_is_gone(name: str) -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(name)


@pytest.mark.parametrize("name", PRESENT)
def test_new_module_imports(name: str) -> None:
    importlib.import_module(name)
