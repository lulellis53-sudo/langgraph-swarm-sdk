"""Model integration domain: chat models, model routing, registry, and circuit breakers."""

from __future__ import annotations

from swarm_sdk.models.breaker import BreakerConfig, BreakerState, CircuitBreaker, CircuitOpenError
from swarm_sdk.models.chat import complete, last_ai_text, load_chat_model, message_text
from swarm_sdk.models.registry import (
    DEFAULT_REGISTRY_PATH,
    Registry,
    RegistryEntry,
    load_registry,
)
from swarm_sdk.models.selection import (
    THINK_TOKEN_BUDGET,
    FallbackChain,
    ModelRoute,
    ModelSelectConfig,
    ModelSelector,
    ThinkLevel,
    bounded_gather,
)

__all__ = [
    "DEFAULT_REGISTRY_PATH",
    "THINK_TOKEN_BUDGET",
    "BreakerConfig",
    "BreakerState",
    "CircuitBreaker",
    "CircuitOpenError",
    "FallbackChain",
    "ModelRoute",
    "ModelSelectConfig",
    "ModelSelector",
    "Registry",
    "RegistryEntry",
    "ThinkLevel",
    "bounded_gather",
    "complete",
    "last_ai_text",
    "load_chat_model",
    "load_registry",
    "message_text",
]
