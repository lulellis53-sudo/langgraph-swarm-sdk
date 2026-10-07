"""CLI entry point: ``python -m WebSearch.docker up|down|status``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from WebSearch.docker import down, status, up


def build_parser() -> argparse.ArgumentParser:
    """Create the subcommand parser."""
    parser = argparse.ArgumentParser(
        description="Manage a local SearXNG container for WebSearch.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    up_parser = sub.add_parser("up", help="Start the SearXNG container")
    up_parser.add_argument(
        "--no-detach",
        action="store_true",
        help="Run in the foreground",
    )

    down_parser = sub.add_parser("down", help="Stop and remove the container")
    down_parser.add_argument(
        "--volumes",
        action="store_true",
        help="Also remove named volumes",
    )

    sub.add_parser("status", help="Show container status")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch to the requested subcommand."""
    args = build_parser().parse_args(argv)

    if args.command == "up":
        return up(detach=not args.no_detach)
    if args.command == "down":
        return down(volumes=args.volumes)
    if args.command == "status":
        return status()
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
