"""Model selection (think level, task routing) and fallback chains with circuit breakers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Literal

from pydantic import BaseModel, Field

from swarm_sdk.models.breaker import BreakerConfig, CircuitBreaker, CircuitOpenError
from swarm_sdk.models.chat import complete_with_usage, load_chat_model

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
    """Think-level routing table (the ``model_select:`` block)."""

    default_level: ThinkLevel = "medium"
    routes: list[ModelRoute] = Field(default_factory=list)


class ModelSelector:
    """Pick the highest-priority route that supports the requested think level."""

    def __init__(self, config: ModelSelectConfig | None = None) -> None:
        """Initialize with an optional route table.

        Args:
            config: Route config; defaults to an empty ``ModelSelectConfig``.
        """
        self.config = config or ModelSelectConfig()

    def select(
        self,
        think_level: ThinkLevel | None = None,
        provider: str | None = None,
    ) -> ModelRoute:
        """Select the best route for a think level (and optional provider).

        Args:
            think_level: Desired think level; defaults to ``config.default_level``.
            provider: Optional provider filter (e.g. ``"openai"``).

        Returns:
            The lowest-priority-number matching ``ModelRoute``.

        Raises:
            ValueError: If no route supports the requested level/provider.
        """
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
        """Build per-provider breakers from the route table.

        Args:
            config: Model routes to try.
            breaker_config: Shared breaker thresholds for each provider.
        """
        self.config = config or ModelSelectConfig()
        self.breakers: dict[str, CircuitBreaker] = {
            route.provider: CircuitBreaker(route.provider, breaker_config)
            for route in self.config.routes
        }

    async def complete(self, system: str, user: str, think_level: ThinkLevel | None = None) -> str:
        """Complete a prompt via the first healthy route; see :meth:`complete_with_usage`."""
        text, _ = await self.complete_with_usage(system, user, think_level)
        return text

    async def complete_with_usage(
        self,
        system: str,
        user: str,
        think_level: ThinkLevel | None = None,
        *,
        json_mode: bool = False,
    ) -> tuple[str, int]:
        """Complete a prompt via the first healthy route that supports ``think_level``.

        Args:
            system: System prompt.
            user: User / packed prompt body.
            think_level: Optional think level filter.
            json_mode: Ask the provider for a JSON object.

        Returns:
            ``(reply text, tokens)`` from the first successful provider.

        Raises:
            ValueError: If no route supports the think level.
            RuntimeError: If every candidate provider fails or is open.
        """
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
                result = await complete_with_usage(model, system, user, json_mode=json_mode)
            except CircuitOpenError:
                continue
            except Exception as exc:  # noqa: BLE001 - any provider error trips the breaker
                breaker.record_failure()
                last_error = exc
                continue
            breaker.record_success()
            return result
        raise RuntimeError(f"all providers failed for think_level={level!r}") from last_error


async def bounded_gather[T](
    coro_factories: Sequence[Callable[[], Awaitable[T]]],
    max_concurrency: int = 8,
) -> list[T]:
    """Gather async factories with a concurrency cap.

    A failing factory cancels its in-flight siblings at once (TaskGroup
    semantics) instead of letting doomed provider calls run to completion;
    on Python 3.15 the group can also be aborted early via ``TaskGroup.cancel``.
    A wave with exactly one failure re-raises that original error so callers
    keep the provider exception, not an ``ExceptionGroup`` wrapper.

    Args:
        coro_factories: Zero-arg callables that return awaitables.
        max_concurrency: Max concurrent tasks (swarm parallelism limit).

    Returns:
        Results in the same order as ``coro_factories``.

    Raises:
        ValueError: If ``max_concurrency`` is less than 1.
    """
    if max_concurrency < 1:
        raise ValueError("max_concurrency must be >= 1")
    semaphore = asyncio.Semaphore(max_concurrency)

    async def run(factory: Callable[[], Awaitable[T]]) -> T:
        async with semaphore:
            return await factory()

    try:
        async with asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(run(f)) for f in coro_factories]
    except BaseExceptionGroup as group:
        if len(group.exceptions) == 1:
            raise group.exceptions[0] from None
        raise
    return [task.result() for task in tasks]


__all__ = [
    "FallbackChain",
    "ModelRoute",
    "ModelSelectConfig",
    "ModelSelector",
    "THINK_TOKEN_BUDGET",
    "ThinkLevel",
    "bounded_gather",
]
