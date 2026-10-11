"""Repeat driver: run the bounded harvest N times in a loop.

Each cycle is one full pass of :mod:`Prediction.BotDeal.harvest_run.main`
(WebSearch dork per SKU -> snippet-price parse -> offers SQLite + Parquet
DB -> floors/alerts rebuild), followed by a polite sleep so the search
backends are not hammered. Search failures in one cycle do not abort the
loop; they are counted and reported at the end.

Run from the BotDeal product checkout so the Parquet database lands in the
product lane:

    PYTHONPATH="$HOME/Myworkspace/Swarm:$HOME/Myworkspace/Swarm/src" \
      python -m Prediction.BotDeal.loop_run --cycles 20
"""

from __future__ import annotations

import argparse
import time

from Prediction.BotDeal.harvest_run import main as harvest_main


def run_loop(
    *,
    cycles: int,
    sleep_s: float,
    harvest_args: list[str],
) -> int:
    """Run ``harvest_main(harvest_args)`` ``cycles`` times with ``sleep_s``
    between cycles. Returns a process exit code (0 unless a cycle raised
    an unexpected non-search error, which aborts)."""
    ok = 0
    failed = 0
    started = time.monotonic()
    for cycle in range(1, cycles + 1):
        cycle_start = time.monotonic()
        print(f"=== cycle {cycle}/{cycles} ===", flush=True)
        try:
            harvest_main(harvest_args)
            ok += 1
        except KeyboardInterrupt:
            print(f"interrupted at cycle {cycle}; {ok} ok, {failed} failed")
            return 130
        except Exception as exc:
            # A hard error (bad catalog, broken DB) is not transient: stop.
            print(f"cycle {cycle}: aborted {type(exc).__name__}: {exc}")
            failed += 1
            break
        print(f"cycle {cycle} done in {time.monotonic() - cycle_start:.1f}s", flush=True)
        if cycle < cycles and sleep_s > 0:
            time.sleep(sleep_s)
    print(f"loop: {ok}/{cycles} ok, {failed} aborted, {time.monotonic() - started:.1f}s total")
    return 0 if failed == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=20)
    parser.add_argument("--sleep", type=float, default=15.0, help="seconds between cycles")
    parser.add_argument(
        "--harvest-args",
        default="--skus rtx-5090,ddr5-32gb --days 7 --limit 10",
        help="args forwarded to harvest_run.main",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="forward --fresh to every cycle so hits bypass the search cache",
    )
    args = parser.parse_args(argv)
    if args.cycles < 1:
        parser.error("--cycles must be >= 1")
    harvest_args = args.harvest_args.split()
    if args.fresh and "--fresh" not in harvest_args:
        harvest_args.append("--fresh")
    return run_loop(
        cycles=args.cycles,
        sleep_s=args.sleep,
        harvest_args=harvest_args,
    )


if __name__ == "__main__":
    raise SystemExit(main())
