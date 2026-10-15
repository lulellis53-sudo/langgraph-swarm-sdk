"""Command groups for the ``low-swarm`` CLI: spawn, swarm, parallel."""

from __future__ import annotations

import argparse
import importlib
from collections.abc import Callable
from typing import Any

type Handler = Callable[[argparse.Namespace, Any], int]


def register_all(subparsers: Any) -> dict[str, Handler]:
    """Register every command group on ``subparsers``; return ``{command: handler}``."""
    from swarm_sdk.commands import parallel, spawn, swarm

    handlers: dict[str, Handler] = {}
    for module in (spawn, swarm, parallel):
        name, handler = module.register(subparsers)
        handlers[name] = handler
    return handlers


def markup_safe(text: str) -> str:
    """Escape Rich markup in untrusted text (LLM output); identity when Rich is absent."""
    try:
        # dynamic import: rich is optional and not installed in all environments; a static
        # import adds a ty unresolved-import diagnostic and ty is held at <= 15
        markup = importlib.import_module("rich.markup")
    except ImportError:
        return text
    return str(markup.escape(text))


__all__ = ["Handler", "markup_safe", "register_all"]
