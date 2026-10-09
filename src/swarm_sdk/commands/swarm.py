"""``low-swarm swarm TEXT``: run one message through the LangGraph handoff swarm."""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import TYPE_CHECKING, Any

from swarm_sdk.cli import create_panel, create_table
from swarm_sdk.commands import Handler, markup_safe

if TYPE_CHECKING:
    from swarm_sdk.core.swarm import SwarmSDK


def register(subparsers: Any) -> tuple[str, Handler]:
    """Add the ``swarm`` subcommand and return its (name, handler) pair.

    Args:
        subparsers: argparse subparsers collection of the root CLI parser.

    Returns:
        Tuple of the command name and the handler bound to it.
    """
    parser = subparsers.add_parser("swarm", help="Run a message through the handoff swarm")
    parser.add_argument("text", help="Message for the swarm")
    parser.add_argument("--thread-id", default="default", help="Conversation thread id")
    return "swarm", handle_swarm


def _build_sdk() -> SwarmSDK:
    from swarm_sdk.core.swarm import SwarmSDK

    return SwarmSDK.from_settings()


def handle_swarm(args: argparse.Namespace, console: Any) -> int:
    """Run the swarm on ``args.text`` and print the summary table and the answer."""
    try:
        result = asyncio.run(_build_sdk().run(args.text, thread_id=args.thread_id))
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    table = create_table(title="Swarm run")
    table.add_column("Dimension", style="bold")
    table.add_column("Result")
    table.add_row("Thread", markup_safe(args.thread_id))
    table.add_row("Active agent", markup_safe(result.active_agent))
    table.add_row("Mode", markup_safe(result.mode))
    table.add_row("Tokens", str(result.tokens))
    table.add_row("Cached", "yes" if result.cached else "no")
    console.print(create_panel(table, title="Swarm"))
    print(result.text)
    return 0
