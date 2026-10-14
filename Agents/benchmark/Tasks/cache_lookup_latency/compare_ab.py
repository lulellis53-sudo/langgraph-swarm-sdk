"""Compare two ``cache_lookup_latency`` reports (baseline A vs candidate B).

Reads the gitignored result JSONs, reports per-size median deltas and percent
improvement for every measured path, and combines the paired ABBA verdicts across
candidate sessions via ``benchmark.stats.combine_sessions``: a speedup claim needs
the same verdict label in every session and a bootstrap interval excluding zero.
A single-process run is never labeled a speedup (Benchmark.md §2.6).
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

from benchmark.stats import combine_sessions

_PATHS = ("exact_hit_us", "semantic_hit_us", "miss_us")


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _by_entries(report: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {int(row["entries"]): row for row in report["results"]}


def compare_sessions(
    baseline: dict[str, Any], candidates: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Compare one baseline report against one or more candidate reports."""
    if not candidates:
        raise ValueError("at least one candidate session is required")
    base = _by_entries(baseline)
    cands = [_by_entries(c) for c in candidates]
    sizes = sorted(base)
    rows: list[dict[str, Any]] = []
    for size in sizes:
        for path in _PATHS:
            a = float(base[size][path]["median"])
            b_medians = [float(c[size][path]["median"]) for c in cands]
            rows.append(
                {
                    "entries": size,
                    "path": path,
                    "baseline_median_us": a,
                    "candidate_median_us": statistics.median(b_medians),
                    "candidate_session_medians_us": b_medians,
                    "delta_pct": statistics.median(b_medians) / a * 100.0 - 100.0 if a else 0.0,
                    "sessions": len(cands),
                }
            )
        verdicts = [c[size]["batch_vs_single"]["verdict"] for c in cands]
        rows.append(
            {
                "entries": size,
                "path": "batch_vs_single_verdict",
                "combined_label": combine_sessions([v["label"] for v in verdicts]),
                "baseline_median_per_query_us": baseline["results"][sizes.index(size)][
                    "batch_vs_single"
                ]["single_median_per_query_us"],
                "candidate_median_per_query_us": statistics.median(
                    [c[size]["batch_vs_single"]["batch_median_per_query_us"] for c in cands]
                ),
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    """Print the A/B table; requires one baseline and one or more candidate JSONs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, help="baseline report JSON (A)")
    parser.add_argument("--candidate", required=True, nargs="+", help="candidate JSONs (B)")
    args = parser.parse_args(argv)
    baseline = _load(Path(args.baseline))
    candidates = [_load(Path(p)) for p in args.candidate]
    print(json.dumps(compare_sessions(baseline, candidates), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
