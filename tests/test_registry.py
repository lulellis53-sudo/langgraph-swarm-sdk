"""Registry loading and ranking."""

from pathlib import Path

import pytest

from swarm_sdk.registry import Registry, RegistryEntry, load_registry

REGISTRY = Path("config/model_registry.yaml")


def test_load_registry_from_default_path() -> None:
    reg = load_registry()
    assert len(reg.providers) >= 18
    names = {entry.name for entry in reg.providers}
    assert "zai:glm-5.3" in names
    assert "google:gemini-3.8-flash" in names


def test_ranked_orders_by_priority() -> None:
    reg = Registry(
        providers=[
            RegistryEntry(name="b", provider="pb", priority=20, think_levels=("high",)),
            RegistryEntry(name="a", provider="pa", priority=10, think_levels=("high",)),
        ]
    )
    assert [e.name for e in reg.ranked("high")] == ["a", "b"]


def test_ranked_filters_by_think_level() -> None:
    reg = Registry(
        providers=[
            RegistryEntry(name="low-only", provider="p", priority=1, think_levels=("low",)),
            RegistryEntry(name="high-only", provider="p", priority=2, think_levels=("high",)),
        ]
    )
    assert [e.name for e in reg.ranked("high")] == ["high-only"]
    assert [e.name for e in reg.ranked("low")] == ["low-only"]


def test_select_best_and_fallback_order() -> None:
    reg = Registry(
        providers=[
            RegistryEntry(name="best", provider="p1", priority=10, think_levels=("high",)),
            RegistryEntry(name="mid", provider="p2", priority=20, think_levels=("high",)),
            RegistryEntry(name="last", provider="p3", priority=30, think_levels=("high",)),
        ]
    )
    assert reg.select_best("high").name == "best"
    assert [e.name for e in reg.fallback_order("high", depth=2)] == ["best", "mid"]


def test_select_best_unknown_level() -> None:
    reg = Registry(providers=[RegistryEntry(name="x", provider="p", think_levels=("low",))])
    with pytest.raises(ValueError, match="no registered model"):
        reg.select_best("xhigh")


def test_routes_feed_model_select_config() -> None:
    cfg = load_registry(REGISTRY).to_model_select_config()
    assert cfg.routes
    assert all(r.priority >= 1 for r in cfg.routes)
