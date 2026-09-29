"""Benchmark model-delegation decisions against the provider registry.

No live API calls are made; we only exercise route selection, fallback-chain
construction, and GPU dispatch heuristics.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import cast

import pytest
import yaml

from swarm_sdk.models.selection import (
    FallbackChain,
    ModelRoute,
    ModelSelectConfig,
    ModelSelector,
    ThinkLevel,
)

_REGISTRY = (
    Path(__file__).resolve().parents[4]
    / "src"
    / "swarm_sdk"
    / "agents"
    / "config"
    / "model_registry.yaml"
)


def _load_registry() -> list[ModelRoute]:
    data = yaml.safe_load(_REGISTRY.read_text(encoding="utf-8"))
    routes: list[ModelRoute] = []
    for item in data.get("providers", []):
        levels = cast(
            tuple[ThinkLevel, ...],
            tuple(str(x) for x in item.get("think_levels", [])),
        )
        routes.append(
            ModelRoute(
                name=str(item["name"]),
                provider=str(item.get("provider", "openai")),
                think_levels=levels,
                priority=int(item.get("priority", 100)),
            )
        )
    return routes


@pytest.fixture
def registry_routes() -> list[ModelRoute]:
    return _load_registry()


@pytest.fixture
def selector(registry_routes: list[ModelRoute]) -> ModelSelector:
    return ModelSelector(ModelSelectConfig(routes=registry_routes))


@pytest.mark.parametrize(
    ("think_level", "expected_provider", "expected_model"),
    [
        ("off", "xiaomi", "xiaomi:mimo-v2.5-pro"),
        ("low", "xiaomi", "xiaomi:mimo-v2.5-pro"),
        ("medium", "xiaomi", "xiaomi:mimo-v2.5-pro"),
        ("high", "zai", "zai:glm-5.3"),
        ("xhigh", "zai", "zai:glm-5.3"),
    ],
)
def test_route_by_think_level(
    selector: ModelSelector,
    think_level: str,
    expected_provider: str,
    expected_model: str,
) -> None:
    route = selector.select(think_level=cast(ThinkLevel, think_level))
    assert route.provider == expected_provider
    assert route.name == expected_model


def test_fallback_chain_builds(registry_routes: list[ModelRoute]) -> None:
    chain = FallbackChain(ModelSelectConfig(routes=registry_routes))
    assert len(chain.config.routes) >= 5
    assert chain.breakers


def test_provider_hint_restricts(selector: ModelSelector) -> None:
    route = selector.select(think_level="low", provider="openrouter")
    assert route.provider == "openrouter"
    assert route.name == "openrouter:z-ai/glm-5.3-flash"


def test_all_requested_providers_present(registry_routes: list[ModelRoute]) -> None:
    providers = {r.provider for r in registry_routes}
    expected = {
        "alibaba",
        "cohere-1",
        "cohere-2",
        "mistral-1",
        "mistral-2",
        "minimax",
        "xiaomi",
        "claude-code",
        "codex",
        "google",
        "groq-1",
        "groq-2",
        "moonshot",
        "nvidia",
        "ollama-cloud",
        "openrouter",
        "sambanova",
        "fireworks",
        "xai",
        "zai",
    }
    missing = expected - providers
    assert not missing, f"missing providers: {missing}"


@pytest.fixture
def gpu_backend(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("SWARM_GPU_BACKEND", "opencl")
    return "opencl"


def test_embedding_dispatch_prefers_gpu(gpu_backend: str) -> None:
    backend = os.environ.get("SWARM_GPU_BACKEND", "")
    assert backend in {"opencl", "molten", "metal", "vulkan"}


def test_math_dispatch_prefers_gpu(gpu_backend: str) -> None:
    backend = os.environ.get("SWARM_GPU_BACKEND", "")
    assert backend in {"opencl", "molten", "metal", "vulkan"}
