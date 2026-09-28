"""Model selection and fallback chain ordering."""

import pytest

from swarm_sdk.model_select import (
    FallbackChain,
    ModelRoute,
    ModelSelectConfig,
    ModelSelector,
)
from swarm_sdk.resilience import BreakerConfig


def routes() -> list[ModelRoute]:
    return [
        ModelRoute(name="p1:fast", provider="p1", priority=10, think_levels=("off", "low")),
        ModelRoute(name="p1:strong", provider="p1", priority=20, think_levels=("high",)),
        ModelRoute(name="p2:strong", provider="p2", priority=30, think_levels=("high", "xhigh")),
        ModelRoute(name="p3:any", provider="p3", priority=40),
    ]


def test_selector_picks_lowest_priority_for_level() -> None:
    selector = ModelSelector(ModelSelectConfig(routes=routes()))
    assert selector.select("low").name == "p1:fast"
    assert selector.select("high").name == "p1:strong"
    assert selector.select("xhigh").name == "p2:strong"


def test_selector_default_level() -> None:
    selector = ModelSelector(ModelSelectConfig(default_level="off", routes=routes()))
    assert selector.select().name == "p1:fast"


def test_selector_filters_by_provider() -> None:
    selector = ModelSelector(ModelSelectConfig(routes=routes()))
    assert selector.select("high", provider="p2").name == "p2:strong"


def test_selector_rejects_unsupported_level() -> None:
    selector = ModelSelector(ModelSelectConfig(routes=routes()))
    with pytest.raises(ValueError, match="no model route"):
        selector.select("off", provider="p2")


@pytest.mark.asyncio
async def test_fallback_skips_open_breaker(monkeypatch: pytest.MonkeyPatch) -> None:
    """The best route's provider breaker is open, so the call lands on the next route."""
    chain = FallbackChain(
        ModelSelectConfig(default_level="high", routes=routes()),
        BreakerConfig(failure_threshold=1),
    )
    chain.breakers["p1"].record_failure()  # trips p1 immediately

    calls: list[str] = []

    class FakeModel:
        def __init__(self, name: str) -> None:
            self.name = name

    async def fake_complete(model, system, user):  # noqa: ANN001
        calls.append(model.name)
        return f"via {model.name}"

    def fake_load(name: str) -> object:
        return FakeModel(name)

    import swarm_sdk.providers as providers

    monkeypatch.setattr(providers, "complete", fake_complete)
    monkeypatch.setattr(providers, "load_chat_model", fake_load)
    result = await chain.complete("sys", "user", think_level="high")
    assert result == "via p2:strong"
    assert calls == ["p2:strong"], "p1 must be skipped, p2 is next at 'high'"


@pytest.mark.asyncio
async def test_fallback_all_open_raises() -> None:
    chain = FallbackChain(
        ModelSelectConfig(default_level="high", routes=routes()),
        BreakerConfig(failure_threshold=1),
    )
    for breaker in chain.breakers.values():
        breaker.record_failure()
    with pytest.raises(RuntimeError, match="all providers failed"):
        await chain.complete("sys", "user", think_level="high")


@pytest.mark.asyncio
async def test_fallback_no_route_for_level() -> None:
    chain = FallbackChain(ModelSelectConfig(routes=[]))
    with pytest.raises(ValueError, match="no route supports"):
        await chain.complete("sys", "user", think_level="medium")
