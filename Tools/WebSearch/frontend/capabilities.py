"""Loader for the machine-readable provider capability registry.

``WebSearch/Config/Providers.json`` records, per searcher/MCP server, the
official-API limits (max query length, result caps, rate limits), request
parameter placeholders, env var names, and documentation URLs. JS consumers
read the JSON directly; Python consumers use :func:`load_capabilities` or
:func:`provider_capabilities`. Undocumented limits are ``null`` — never guess.
"""

from __future__ import annotations

lazy import json
lazy from functools import lru_cache
lazy from importlib.resources import files
lazy from pathlib import Path
lazy from typing import Any


def capabilities_path() -> Path:
    """Path to the packaged ``Config/Providers.json`` capability registry."""
    return Path(str(files("WebSearch").joinpath("Config", "Providers.json")))


@lru_cache(maxsize=1)
def load_capabilities() -> dict[str, Any]:
    """Parse the capability registry (cached per process).

    Returns:
        dict[str, Any]: The full document (``version`` + ``providers`` map).
    """
    return json.loads(capabilities_path().read_text(encoding="utf-8"))


def provider_capabilities(provider_id: str) -> dict[str, Any]:
    """Capability block for one provider/MCP id.

    Args:
        provider_id (str): Registry id (e.g. ``tavily``, ``ddg_mcp``).

    Returns:
        dict[str, Any]: The provider's settings (kind, docs, limits, placeholders).

    Raises:
        KeyError: If the id is absent from the registry.
    """
    providers = load_capabilities()["providers"]
    try:
        return providers[provider_id]
    except KeyError:
        raise KeyError(f"unknown provider in Config/Providers.json: {provider_id!r}") from None


__all__ = ["capabilities_path", "load_capabilities", "provider_capabilities"]
