"""Model selection (think level, task routing) and fallback chains with circuit breakers."""

from __future__ import annotations

import asyncio
from typing import Literal

from pydantic import BaseModel, Field

from swarm_sdk.resilience import BreakerConfig, CircuitBreaker, CircuitOpenError

ThinkLevel = Literal["off", "low", "medium", "high", "xhigh"]

# Rough mapping of think levels to per-call token budgets.
THINK_TOKEN_BUDGET: dict[str, int] = {
    "off": 0,
    "low": 512,
    "medium": 2048,
    "high": 8192,
    "xhigh": 32768,
}


class ModelRoute(BaseModel):
    """One candidate model. `name` is a LangChain init_chat_model string, e.g. 'openai:gpt-4o'."""

    name: str
    provider: str = "openai"
    think_levels: tuple[ThinkLevel, ...] = ("off", "low", "medium", "high", "xhigh")
    priority: int = 100  # lower = tried first


class ModelSelectConfig(BaseModel):
    default_level: ThinkLevel = "medium"
    routes: list[ModelRoute] = Field(default_factory=list)


class ModelSelector:
    """Pick the highest-priority route that supports the requested think level."""

    def __init__(self, config: ModelSelectConfig | None = None) -> None:
        self.config = config or ModelSelectConfig()

    def select(
        self,
        think_level: ThinkLevel | None = None,
        provider: str | None = None,
    ) -> ModelRoute:
        level = think_level or self.config.default_level
        candidates = [r for r in self.config.routes if level in r.think_levels]
        if provider:
            candidates = [r for r in candidates if r.provider == provider]
        if not candidates:
            raise ValueError(f"no model route supports think_level={level!r}")
        return min(candidates, key=lambda r: r.priority)


class FallbackChain:
    """Try models in priority order; skip providers whose circuit breaker is open."""

    def __init__(
        self,
        config: ModelSelectConfig | None = None,
        breaker_config: BreakerConfig | None = None,
    ) -> None:
        self.config = config or ModelSelectConfig()
        self.breakers: dict[str, CircuitBreaker] = {
            route.provider: CircuitBreaker(route.provider, breaker_config)
            for route in self.config.routes
        }

    async def complete(self, system: str, user: str, think_level: ThinkLevel | None = None) -> str:
        from swarm_sdk.providers import complete, load_chat_model

        level = think_level or self.config.default_level
        ordered = sorted(
            (r for r in self.config.routes if level in r.think_levels),
            key=lambda r: r.priority,
        )
        if not ordered:
            raise ValueError(f"no route supports think_level={level!r}")

        last_error: Exception | None = None
        for route in ordered:
            breaker = self.breakers.setdefault(route.provider, CircuitBreaker(route.provider))
            try:
                breaker.before_call()
            except CircuitOpenError:
                continue  # provider is down, fall through to next route
            try:
                model = load_chat_model(route.name)
                result = await complete(model, system, user)
            except CircuitOpenError:
                continue
            except Exception as exc:  # noqa: BLE001 - any provider error trips the breaker
                breaker.record_failure()
                last_error = exc
                continue
            breaker.record_success()
            return result
        raise RuntimeError(f"all providers failed for think_level={level!r}") from last_error


async def bounded_gather(coro_factories: list, max_concurrency: int = 8) -> list:
    """Gather with a concurrency cap (swarm parallelism limit)."""
    semaphore = asyncio.Semaphore(max_concurrency)

    async def run(factory):
        async with semaphore:
            return await factory()

    return await asyncio.gather(*(run(f) for f in coro_factories))


__all__ = [
    "FallbackChain",
    "ModelRoute",
    "ModelSelectConfig",
    "ModelSelector",
    "THINK_TOKEN_BUDGET",
    "ThinkLevel",
    "bounded_gather",
]
