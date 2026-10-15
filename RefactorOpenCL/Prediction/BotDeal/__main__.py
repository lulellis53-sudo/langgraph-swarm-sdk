"""``python -m Prediction.BotDeal mcp|harvest|hardware …``"""

from __future__ import annotations

import argparse

from Prediction.BotDeal._entry import mcp_main, run_harvest
from Prediction.br_hardware import main as br_hardware_main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BotDeal — BR hardware deal pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("mcp", help="stdio MCP server (promodeals_mcp)")
    sub.add_parser("harvest", help="WebSearch harvest into offers.db")
    hardware = sub.add_parser("hardware", help="pass-through to Prediction.br_hardware")
    hardware.add_argument("br_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.command == "mcp":
        mcp_main()
        return 0
    if args.command == "harvest":
        return run_harvest()
    br_argv = [a for a in args.br_args if a != "--"]
    br_hardware_main(br_argv if br_argv else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
