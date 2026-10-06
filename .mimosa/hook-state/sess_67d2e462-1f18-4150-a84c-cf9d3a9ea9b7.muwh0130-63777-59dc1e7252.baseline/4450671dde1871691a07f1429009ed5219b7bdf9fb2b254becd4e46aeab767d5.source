"""CLI entrypoint for the SQL Pro benchmarkable suite."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from benchmark.sql_pro.harness import SqlProSuite, load_suite

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results" / "sql_pro"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run SQL Pro benchmarkable suite")
    parser.add_argument(
        "--suite",
        type=Path,
        default=None,
        help="Path to suite.yaml (default: benchmark/sql_pro/suite.yaml)",
    )
    parser.add_argument("--json", action="store_true", help="Emit results as JSON")
    parser.add_argument(
        "--write-results",
        action="store_true",
        help="Write JSON results to benchmark/results/sql_pro/ (gitignored)",
    )
    parser.add_argument("--case", action="append", default=[], help="Run only these case ids")
    args = parser.parse_args(argv)

    suite_doc = load_suite(args.suite)
    runner = SqlProSuite(suite_doc)
    if args.case:
        id_set = set(args.case)
        runner.cases = [c for c in runner.cases if c["id"] in id_set]

    results = runner.run_all()
    failed = [r for r in results if not r.passed]
    payload = [r.to_dict() for r in results]

    if args.write_results:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        out_path = RESULTS_DIR / f"{stamp}.json"
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"wrote {out_path}")

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        for result in results:
            status = "PASS" if result.passed else "FAIL"
            print(f"{status}\t{result.case_id}\t{result.latency_ms:.3f}ms\trows={result.row_count}")
            if result.notes:
                for note in result.notes:
                    print(f"  note: {note}")
            if result.error:
                print(f"  error: {result.error}")

    if failed:
        print(f"{len(failed)} case(s) failed", file=sys.stderr)
        return 1
    print(f"OK: {len(results)} case(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
