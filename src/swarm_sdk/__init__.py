"""LangGraph swarm SDK with memory, reranking, token budgets, and semantic cache.

Heavy imports (pydantic_settings, langchain) are deferred to first attribute
access so ``import swarm_sdk`` stays fast for CLI tools and tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = ["RunResult", "Settings", "SwarmSDK"]
__version__ = "0.1.0"

if TYPE_CHECKING:
    from swarm_sdk.config.settings import Settings
    from swarm_sdk.core.swarm import RunResult, SwarmSDK

_LAZY: dict[str, tuple[str, str]] = {
    "Settings": ("swarm_sdk.config.settings", "Settings"),
    "SwarmSDK": ("swarm_sdk.core.swarm", "SwarmSDK"),
    "RunResult": ("swarm_sdk.core.swarm", "RunResult"),
}


def __getattr__(name: str) -> Any:
    """Lazy-import public names on first access."""
    if name in _LAZY:
        module_path, attr = _LAZY[name]
        from importlib import import_module

        module = import_module(module_path)
        value = getattr(module, attr)
        # Cache on the module so subsequent lookups skip __getattr__.
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
