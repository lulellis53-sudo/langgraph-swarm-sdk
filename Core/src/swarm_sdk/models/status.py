"""Provider route readiness without exposing credential values."""

from __future__ import annotations

import importlib.util
import shutil
from collections import defaultdict
from typing import TypedDict

from swarm_sdk.models.chat import Route, _route_index, route_is_ready
from swarm_sdk.models.cli_chat import CLI_PROVIDERS


class ProviderStatus(TypedDict):
    """Safe, user-facing status for one provider family."""

    provider: str
    models: list[str]
    credential_env: list[str]
    configured: bool
    installed: bool


_PROVIDER_MODULES = {
    "anthropic": "langchain_anthropic",
    "claude-code": "claude",
    "cohere": "langchain_cohere",
    "codex": "codex",
    "google": "langchain_google_genai",
    "groq": "langchain_groq",
    "mistral": "langchain_mistralai",
    "openai": "langchain_openai",
    "grok-cli": "grok",
    "openrouter": "langchain_openai",
    "sambanova": "langchain_openai",
    "fireworks": "langchain_openai",
    "zai": "langchain_openai",
    "minimax": "langchain_openai",
    "moonshot": "langchain_openai",
    "xiaomi": "langchain_openai",
    "nvidia": "langchain_openai",
    "atlascloud": "langchain_openai",
    "poolside": "langchain_openai",
    "ollama-cloud": "langchain_openai",
    "ollama": "langchain_openai",
    "alibaba": "langchain_openai",
    "xai": "langchain_openai",
}
_CLI_PROVIDERS = {
    "claude-cli": "claude",
    "claude-code": "claude",
    "codex-cli": "codex",
    "codex": "codex",
    "grok-cli": "grok",
}


def provider_status() -> list[ProviderStatus]:
    """Return readiness for model providers registered in the packaged model catalog.

    Credential values are only checked for presence. The result includes environment
    variable names so users can identify which credential to configure.
    """
    grouped: dict[str, list[tuple[str, Route]]] = defaultdict(list)
    for model_name, route in _route_index().items():
        provider, separator, _ = model_name.partition(":")
        if separator:
            grouped[provider].append((model_name, route))

    rows: list[ProviderStatus] = []
    for provider, routes in sorted(grouped.items()):
        models = sorted(model for model, _ in routes)
        credentials = sorted(
            {
                name
                for _, route in routes
                for name in (route.api_key_env, *route.key_fallbacks)
                if name
            }
        )
        configured = any(route_is_ready(model) for model in models)
        if provider in CLI_PROVIDERS or provider in _CLI_PROVIDERS:
            binary = _CLI_PROVIDERS.get(provider, provider.removesuffix("-cli"))
            installed = shutil.which(binary) is not None
        else:
            module = _PROVIDER_MODULES.get(provider)
            if module in _CLI_PROVIDERS.values():
                installed = shutil.which(module) is not None
            else:
                installed = module is not None and importlib.util.find_spec(module) is not None
        rows.append(
            {
                "provider": provider,
                "models": models,
                "credential_env": credentials,
                "configured": configured,
                "installed": installed,
            }
        )
    return rows


__all__ = ["ProviderStatus", "provider_status"]
