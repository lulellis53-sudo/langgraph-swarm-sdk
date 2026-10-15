"""Pins the merged package layout: shipped modules import, retired packages are gone."""

from __future__ import annotations

import importlib

import pytest

REMOVED: list[str] = [
    # The runtime/ package was folded into execution/ (concurrency, executor,
    # fanout, usage) after the agents merge; nothing may import it again.
    "swarm_sdk.runtime",
    "swarm_sdk.runtime.concurrency",
    "swarm_sdk.runtime.executor",
    "swarm_sdk.runtime.fanout",
    "swarm_sdk.runtime.metrics",
    "swarm_sdk.runtime.tracing",
    "swarm_sdk.runtime.usage",
    # compute/ was planned but never shipped; scoring lives in execution/ and
    # math/ instead.
    "swarm_sdk.compute",
    "swarm_sdk.compute.scoring",
    "swarm_sdk.compute.lazy_dispatcher",
    "swarm_sdk.compute.opencl_math",
    "swarm_sdk.compute.report",
    "swarm_sdk.serving.graphs",
    "swarm_sdk.models.budget",
]
PRESENT: list[str] = [
    "swarm_sdk.cli",
    "swarm_sdk.decorators",
    "swarm_sdk.netguard",
    "swarm_sdk.redact",
    "swarm_sdk.vault",
    "swarm_sdk.agents.manifest",
    "swarm_sdk.commands.parallel",
    "swarm_sdk.config.settings",
    "swarm_sdk.core.swarm",
    "swarm_sdk.core.factories",
    "swarm_sdk.core.prompts",
    "swarm_sdk.execution",
    "swarm_sdk.execution.concurrency",
    "swarm_sdk.gpu",
    "swarm_sdk.math",
    "swarm_sdk.memory.sqlite_vec",
    "swarm_sdk.models.chat",
    "swarm_sdk.models.selection",
    "swarm_sdk.observability",
    "swarm_sdk.orchestrator.graph",
    "swarm_sdk.orchestrator.plan",
    "swarm_sdk.orchestrator.spawn",
    "swarm_sdk.prediction",
    "swarm_sdk.prompting.budget",
    "swarm_sdk.retrieval.cache",
    "swarm_sdk.search",
    "swarm_sdk.server",
    "swarm_sdk.serving.http",
    "swarm_sdk.serving.grpc",
    "swarm_sdk.tuning",
]


@pytest.mark.parametrize("name", REMOVED)
def test_old_package_is_gone(name: str) -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(name)


@pytest.mark.parametrize("name", PRESENT)
def test_new_module_imports(name: str) -> None:
    importlib.import_module(name)
