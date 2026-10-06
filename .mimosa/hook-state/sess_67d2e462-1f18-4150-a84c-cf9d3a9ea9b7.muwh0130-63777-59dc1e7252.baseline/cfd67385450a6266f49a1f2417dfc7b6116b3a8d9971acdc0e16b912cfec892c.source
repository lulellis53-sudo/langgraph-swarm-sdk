"""Measure the runtime claims of Documents/Python3.15.md §11 on this host.

Canonical dossier paths: ``~/Swarm/Documents/Python3.15.md`` and personal mirror
``~/Documentos/Python3.15.md``. Section §11.3 documents how to run this harness.

Each workload prints *measured* numbers (median of several runs) next to the
speedup the dossier claims. Nothing is hardcoded except the dossier's claimed
speedups, which are kept only for comparison. A workload that cannot run here
(missing interpreter, package or free-threaded build) is reported as
``skipped`` with the reason rather than estimated.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import sysconfig
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from swarm_sdk.core.compression import ZstdStateCompressor
from swarm_sdk.core.minimalloc import Buffer, MiniMalloc

SEED = 7
_RESULTS = Path(__file__).resolve().parents[2] / "results" / "python315_claims"
_PY315 = Path(
    os.environ.get("SWARM_PY315", "~/.local/opt/python-3.15-g6413901/bin/python3.15")
).expanduser()
# Modules heavy enough for import cost to show; all stdlib so any interpreter runs them.
LAZY_MODULES = ("asyncio", "decimal", "email.message", "http.client", "sqlite3", "unittest")


def _median_s(fn: Callable[[], object], repeats: int) -> float:
    """Return the median wall time in seconds of ``repeats`` calls to ``fn``."""
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - start)
    return statistics.median(samples)


def _row(
    wid: str,
    title: str,
    baseline: str,
    target: str,
    unit: str,
    base: float,
    tgt: float,
    claim_speedup: float,
    note: str = "",
) -> dict[str, Any]:
    """Build one report row, computing the measured speedup from base and target times."""
    return {
        "id": wid,
        "title": title,
        "status": "measured",
        "baseline_label": baseline,
        "target_label": target,
        "unit": unit,
        "baseline": base,
        "target": tgt,
        "delta_pct": (tgt - base) / base * 100.0 if base else 0.0,
        "speedup": base / tgt if tgt else float("inf"),
        "claimed_speedup": claim_speedup,
        "note": note,
    }


def _skipped(wid: str, title: str, reason: str) -> dict[str, Any]:
    """Build a report row for a workload that could not run, with the reason."""
    return {"id": wid, "title": title, "status": "skipped", "note": reason}


def _burn(n: int) -> int:
    """CPU-bound loop of ``n`` iterations used as the thread-scaling workload."""
    total = 0
    for i in range(n):
        total += i * i % 7
    return total


def bench_thread_scaling(work: int, repeats: int) -> dict[str, Any]:
    """Workload B: fixed pure-Python CPU work split over 1..12 threads."""
    title = "Multi-core thread scaling (fixed total work)"
    gil = sys._is_gil_enabled()
    times: dict[int, float] = {}
    for n in (1, 2, 4, 6, 12):
        chunk = work // n

        def run(n: int = n, chunk: int = chunk) -> None:
            """Start ``n`` threads that each burn ``chunk`` iterations, then join them."""
            threads = [threading.Thread(target=_burn, args=(chunk,)) for _ in range(n)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        times[n] = _median_s(run, repeats)
    row = _row(
        "B",
        title,
        "1 thread",
        "12 threads",
        "s",
        times[1],
        times[12],
        10.80,
        note=(
            f"gil_enabled={gil}; Py_GIL_DISABLED={sysconfig.get_config_var('Py_GIL_DISABLED')}. "
            "The 10.8x claim needs a free-threaded build and exceeds the 6 physical cores."
        ),
    )
    row["per_thread_count_s"] = {str(k): round(v, 4) for k, v in times.items()}
    row["free_threaded_build"] = not gil
    return row


def bench_vector_dot(n: int, repeats: int) -> dict[str, Any]:
    """Compare a pure-Python dot product against NumPy on ``n`` elements."""
    rng = np.random.default_rng(SEED)
    a, b = rng.random(n), rng.random(n)
    la, lb = a.tolist(), b.tolist()
    base = _median_s(lambda: sum(x * y for x, y in zip(la, lb, strict=True)), repeats)
    tgt = _median_s(lambda: float(np.dot(a, b)), repeats * 5)
    return _row(
        "dot",
        f"Dot product, {n:,} float64",
        "Python scalar loop",
        "numpy.dot (BLAS)",
        "s",
        base,
        tgt,
        103.6,
        "numpy BLAS is the AVX2 path available here; no hand-written SIMD kernel measured",
    )


def bench_stats(n: int, repeats: int) -> dict[str, Any]:
    """Compare mean/variance/median in pure Python against NumPy on ``n`` samples."""
    rng = np.random.default_rng(SEED)
    arr = rng.random(n)
    values = arr.tolist()

    def python_stats() -> tuple[float, float, float]:
        """Compute mean, variance and median with plain Python."""
        mean = sum(values) / n
        var = sum((v - mean) ** 2 for v in values) / n
        return mean, var, sorted(values)[n // 2]

    def numpy_stats() -> tuple[float, float, float]:
        """Compute mean, variance and median with NumPy."""
        return float(arr.mean()), float(arr.var()), float(np.quantile(arr, 0.5))

    try:
        # Optional benchmark dependency, absent from the dev environment.
        import pyarrow  # noqa: F401  # ty: ignore[unresolved-import]
        import pyarrow.compute as pc  # ty: ignore[unresolved-import]

        table = pyarrow.array(arr)

        def target() -> object:
            """Compute mean, variance and approximate median with Arrow compute."""
            return pc.mean(table), pc.variance(table), pc.approximate_median(table)

        label = "pyarrow.compute"
    except ImportError:
        target = numpy_stats
        label = "numpy (pyarrow not installed)"
    base = _median_s(python_stats, max(2, repeats // 2))
    tgt = _median_s(target, repeats * 3)
    return _row("D", f"Columnar stats, {n:,} floats", "Python loop", label, "s", base, tgt, 16.55)


def bench_minimalloc() -> dict[str, Any]:
    """Time the MiniMalloc buffer-placement solver on a fixed buffer set."""
    kb = 1024
    buffers = [
        Buffer("T0", 0, 2, 4 * kb),
        Buffer("T1", 1, 4, 8 * kb),
        Buffer("T2", 2, 5, 4 * kb),
        Buffer("T3", 4, 6, 8 * kb),
        Buffer("T4", 5, 7, 4 * kb),
        Buffer("T5", 6, 8, 8 * kb),
    ]
    solution = MiniMalloc().solve(buffers)
    row = _row(
        "C",
        "Static buffer compaction (6 buffers)",
        "sequential",
        "MiniMalloc",
        "bytes",
        float(solution.uncompacted_bytes),
        float(solution.peak_height),
        3.00,
        "buffer lifetimes are this benchmark's own; the dossier does not give them",
    )
    row["verified"] = solution.verified
    row["optimality_gap_pct"] = solution.optimality_gap_pct
    return row


def bench_zstd(repeats: int) -> dict[str, Any]:
    """Measure zstd state-compression ratio and speed on a fixed 64 KiB text."""
    rng = np.random.default_rng(SEED)
    words = [f"w{int(i)}" for i in rng.integers(0, 400, 20000)]
    text = " ".join(words)[: 64 * 1024].encode()
    comp = ZstdStateCompressor(level=3)
    packed = comp.compress(text)
    assert comp.decompress(packed) == text
    elapsed = _median_s(lambda: comp.compress(text), repeats * 5)
    row = _row(
        "E",
        "Compress 64 KiB synthetic context",
        "raw",
        f"zstd ({comp.backend_name})",
        "bytes",
        float(len(text)),
        float(len(packed)),
        43.12,
        "ratio depends on the corpus: this is a 400-word random vocabulary, not real agent state",
    )
    row["compress_ms"] = round(elapsed * 1000, 3)
    return row


def _startup_ms(python: str, code: str, runs: int) -> float:
    """Return the median wall time in ms of ``runs`` fresh interpreters running ``code``."""
    samples = []
    for _ in range(runs):
        start = time.perf_counter()
        subprocess.run([python, "-c", code], check=True, capture_output=True, timeout=60)
        samples.append((time.perf_counter() - start) * 1000.0)
    return statistics.median(samples)


def bench_lazy_imports(runs: int) -> dict[str, Any]:
    """Compare cold-start time of eager imports against PEP 810 lazy imports on 3.15."""
    title = "Cold start: eager vs PEP 810 lazy imports"
    python = str(_PY315)
    if not _PY315.is_file():
        return _skipped("F", title, f"no Python 3.15 interpreter at {python}")
    eager = "".join(f"import {m}\n" for m in LAZY_MODULES)
    lazy = "".join(f"lazy import {m}\n" for m in LAZY_MODULES)
    try:
        base = _startup_ms(python, eager, runs)
        tgt = _startup_ms(python, lazy, runs)
    except subprocess.CalledProcessError as exc:
        return _skipped("F", title, f"3.15 rejected the snippet: {exc.stderr[-200:]!r}")
    return _row(
        "F",
        title,
        "eager imports",
        "lazy imports",
        "ms",
        base,
        tgt,
        8.42,
        f"interpreter {_PY315.name}; stdlib modules {', '.join(LAZY_MODULES)}; "
        "PEP 810 lazy import syntax; includes interpreter startup, so the ratio is diluted",
    )


def bench_allocator() -> dict[str, Any]:
    """Report the allocator claim as skipped: no mimalloc binding on this host."""
    return _skipped(
        "A",
        "malloc vs mimalloc allocation throughput",
        "mimalloc is not installed (no Python binding or libmimalloc on this host)",
    )


def run(*, quick: bool = False) -> dict[str, Any]:
    """Run every claim workload and return the report; ``quick`` shrinks the sizes."""
    repeats = 3 if quick else 7
    rows = [
        bench_allocator(),
        bench_thread_scaling(1_500_000 if quick else 6_000_000, repeats),
        bench_minimalloc(),
        bench_stats(200_000 if quick else 1_000_000, repeats),
        bench_zstd(repeats),
        bench_lazy_imports(3 if quick else 9),
        bench_vector_dot(200_000 if quick else 1_000_000, repeats),
    ]
    return {
        "dossier": {
            "section": "Documents/Python3.15.md §11",
            "mirror": "~/Documentos/Python3.15.md",
            "verification": "§11.3",
        },
        "host": {
            "machine": platform.machine(),
            "cpu_count": os.cpu_count(),
            "python": platform.python_version(),
            "gil_enabled": sys._is_gil_enabled(),
            "py315": str(_PY315) if _PY315.is_file() else None,
        },
        "method": (
            "median of N runs, time.perf_counter; claimed_speedup is from Python3.15.md §11.2"
        ),
        "quick": quick,
        "rows": rows,
    }


def format_table(report: dict[str, Any]) -> str:
    """Format the report rows as a fixed-width text table."""
    lines = [f"{'id':<4}{'workload':<46}{'measured x':>12}{'claimed x':>11}  note"]
    for r in report["rows"]:
        if r["status"] != "measured":
            lines.append(f"{r['id']:<4}{r['title']:<46}{'skipped':>12}{'':>11}  {r['note']}")
            continue
        lines.append(
            f"{r['id']:<4}{r['title']:<46}{r['speedup']:>12.2f}{r['claimed_speedup']:>11.2f}"
        )
    return "\n".join(lines)


def main() -> int:
    """CLI entry: run the benchmark, print the table, optionally write JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="small sizes for CI")
    parser.add_argument("--json", type=Path, help="also write the full report here")
    parser.add_argument(
        "--write-results",
        action="store_true",
        help="write JSON to Agents/benchmark/results/python315_claims/latest.json",
    )
    args = parser.parse_args()
    report = run(quick=args.quick)
    print(format_table(report))
    if args.write_results:
        out = _RESULTS / "latest.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2))
        print(f"wrote {out}")
    if args.json:
        args.json.write_text(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
