"""Keychain and environment variable resolution for searcher API keys."""

from __future__ import annotations

import logging
import os
from functools import lru_cache

from WebSearch.frontend.types import SearcherSpec

logger = logging.getLogger(__name__)


@lru_cache(maxsize=64)
def _keychain_secret(name: str) -> str:
    """Read the named credential through the shared dedicated-Keychain vault."""
    from swarm_sdk import vault

    return vault.get(name) or ""


def _resolve_secret(name: str) -> str:
    return os.environ.get(name, "").strip() or _keychain_secret(name)


def env_keys(spec: SearcherSpec) -> list[str]:
    """Resolve every configured API key in order: the primary, then the fallbacks.

    Each name is read from the environment, then the Keychain. Names that do not resolve
    and duplicate values are skipped.
    """
    keys: list[str] = []
    for name in (spec.api_key_env, *spec.api_key_fallback_envs):
        value = _resolve_secret(name) if name else ""
        if value and value not in keys:
            keys.append(value)
    return keys


def env_key(spec: SearcherSpec) -> str:
    """The first usable API key of ``spec`` (primary, else a fallback), or ``""``."""
    keys = env_keys(spec)
    return keys[0] if keys else ""


def env_base(spec: SearcherSpec) -> str:
    """Resolve the searcher base URL from env var or spec field."""
    if spec.base_url_env:
        return os.environ.get(spec.base_url_env, "").strip().rstrip("/")
    return (spec.base_url or "").rstrip("/")
