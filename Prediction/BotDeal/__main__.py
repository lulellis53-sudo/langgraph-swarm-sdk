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
    run_parser = sub.add_parser("run", help="one full run: search → observe → forecast")
    run_parser.add_argument("--db", default="offers.db")
    run_parser.add_argument("--lookback-days", type=int, default=7)
    run_parser.add_argument("--sku", action="append", dest="skus", default=None)
    run_parser.add_argument("--limit", type=int, default=10)
    run_parser.add_argument("--horizon", type=int, default=7)
    run_parser.add_argument("--scrape-top", type=int, default=3)
    run_parser.add_argument("--dry-run", action="store_true")
    run_parser.add_argument("--json", action="store_true")
    hardware = sub.add_parser("hardware", help="pass-through to Prediction.br_hardware")
    hardware.add_argument("br_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.command == "mcp":
        mcp_main()
        return 0
    if args.command == "harvest":
        return run_harvest()
    if args.command == "run":
        from Prediction.BotDeal.run import main as run_main

        run_argv = [
            "--db",
            args.db,
            "--lookback-days",
            str(args.lookback_days),
            "--limit",
            str(args.limit),
            "--horizon",
            str(args.horizon),
            "--scrape-top",
            str(args.scrape_top),
        ]
        for sku in args.skus or []:
            run_argv += ["--sku", sku]
        if args.dry_run:
            run_argv.append("--dry-run")
        if args.json:
            run_argv.append("--json")
        return run_main(run_argv)
    br_argv = [a for a in args.br_args if a != "--"]
    br_hardware_main(br_argv if br_argv else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
