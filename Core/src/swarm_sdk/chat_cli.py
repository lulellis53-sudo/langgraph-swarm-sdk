"""Interactive terminal chat for the manifest-driven swarm SDK."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable, Sequence
from typing import Protocol


class TurnResult(Protocol):
    """The part of a swarm turn result displayed by this CLI."""

    text: str


class ChatRunner(Protocol):
    """The SDK interface used by the terminal loop."""

    async def run(self, text: str, thread_id: str) -> TurnResult:
        """Run one user turn and return its response."""


def _read_line(prompt: str) -> str | None:
    """Read a terminal line, returning ``None`` for EOF or Ctrl-C."""
    try:
        return input(prompt)
    except EOFError, KeyboardInterrupt:
        return None


async def chat_loop(
    sdk: ChatRunner,
    *,
    thread_id: str = "cli-thread",
    input_fn: Callable[[str], str | None] = _read_line,
    output_fn: Callable[[str], None] = print,
) -> int:
    """Run the interactive chat loop until the user exits or closes stdin."""
    output_fn("Type a message, or 'exit' to quit.")
    while True:
        message = input_fn("you > ")
        if message is None:
            return 0
        message = message.strip()
        if not message:
            continue
        if message.lower() in {"exit", "quit"}:
            return 0
        result = await sdk.run(message, thread_id)
        output_fn(f"\nswarm > {result.text}\n")


def main(argv: Sequence[str] | None = None) -> int:
    """Start an interactive session using the configured model route."""
    parser = argparse.ArgumentParser(prog="swarm-chat", description="Chat with the Swarm SDK.")
    parser.add_argument("--thread-id", default="cli-thread", help="Conversation thread id.")
    parser.add_argument(
        "--model",
        default=None,
        help="Override every agent's model route for this session.",
    )
    args = parser.parse_args(argv)

    from swarm_sdk.config.settings import Settings
    from swarm_sdk.core.swarm import SwarmSDK

    settings = Settings()
    if args.model:
        settings.model = args.model
    sdk = SwarmSDK.from_settings(settings)
    model = settings.model or settings.router_model
    print(f"Swarm chat using {model}.")
    return asyncio.run(chat_loop(sdk, thread_id=args.thread_id))


__all__ = ["ChatRunner", "TurnResult", "chat_loop", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
