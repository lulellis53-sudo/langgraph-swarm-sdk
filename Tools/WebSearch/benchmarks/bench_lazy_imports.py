"""Benchmark PEP 810 ``lazy import`` in WebSearch against the same source imported eagerly.

Python 3.15 has no "never lazy" switch, but ``sys.set_lazy_imports_filter`` can veto laziness:
a filter that returns ``False`` makes every ``lazy import`` load immediately. So both variants
run the *identical* source in a fresh interpreter, which is the only difference being measured.
Samples follow an ABBA cadence (even rounds A,B,B,A; odd rounds B,A,A,B) and are summarised by
medians, so drift and a loaded machine cannot land on only one variant.

Run: ``python -m WebSearch.benchmarks.bench_lazy_imports [--rounds N] [--json]``.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass

ENTRY_POINTS = (
    "WebSearch.agents.agent_tools",
    "WebSearch.app.cli",
    "WebSearch.midend.crawl",
    "WebSearch.app.api",
)

#: Third-party roots whose presence in ``sys.modules`` shows a heavy dependency was loaded.
TRACKED_ROOTS = (
    "tiktoken",
    "httpx",
    "pydantic",
    "regex",
    "yaml",
    "selectolax",
    "fastapi",
    "pandas",
    "langchain_core",
    "swarm_sdk",
)

#: What a real caller does right after importing; deferred imports are paid here.
FIRST_USE = {
    "WebSearch.agents.agent_tools": (
        "WebSearch.agents.agent_tools.count_tokens('lazy imports')"
    ),
    "WebSearch.app.cli": "WebSearch.app.cli.build_parser()",
    "WebSearch.midend.crawl": "WebSearch.midend.crawl.crawl_then_scrape",
    "WebSearch.app.api": "WebSearch.app.api.app",
}

_CHILD = """
import json, sys, time
if {eager}:
    sys.set_lazy_imports_filter(lambda *args: False)  # False -> import now, not lazily
start = time.perf_counter()
import {entry}
import_ms = (time.perf_counter() - start) * 1000
{use}
ms = (time.perf_counter() - start) * 1000
roots = {{m.split('.')[0] for m in sys.modules}}
print(json.dumps({{"ms": ms, "import_ms": import_ms, "modules": len(sys.modules),
                  "tracked": sorted(r for r in {tracked!r} if r in roots)}}))
"""


@dataclass(frozen=True)
class Row:
    """Measured cost of one entry point, eager versus lazy."""

    entry: str
    eager_ms: float
    lazy_ms: float
    improvement_pct: float
    eager_modules: int
    lazy_modules: int
    eager_tracked: list[str]
    lazy_tracked: list[str]
    eager_first_use_ms: float
    lazy_first_use_ms: float
    first_use_improvement_pct: float


def probe(entry: str, *, eager: bool, use: bool = False) -> dict[str, object]:
    """Import ``entry`` once in a fresh interpreter and report its cost.

    Args:
        entry: Dotted module path to import.
        eager: Veto laziness with the lazy-imports filter when true.
        use: Also perform the entry's first real use inside the timed region, so work a lazy
            import merely defers is still counted.

    Returns:
        ``{"ms": float (import, plus first use when ``use``), "import_ms": float,
        "modules": int, "tracked": [third-party roots loaded]}``.

    Raises:
        subprocess.CalledProcessError: When the child exits non-zero.
        subprocess.TimeoutExpired: When the child exceeds 300 seconds.
    """
    code = _CHILD.format(
        eager=eager,
        entry=entry,
        tracked=TRACKED_ROOTS,
        use=FIRST_USE[entry] if use else "pass",
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, timeout=300
    )
    return json.loads(proc.stdout.strip().splitlines()[-1])


def abba(
    time_a: Callable[[], float], time_b: Callable[[], float], rounds: int
) -> tuple[list[float], list[float]]:
    """Collect paired samples; samples stay with the variant that produced them."""
    a_samples: list[float] = []
    b_samples: list[float] = []
    for index in range(rounds):
        order = ("a", "b", "b", "a") if index % 2 == 0 else ("b", "a", "a", "b")
        for variant in order:
            if variant == "a":
                a_samples.append(time_a())
            else:
                b_samples.append(time_b())
    return a_samples, b_samples


def measure(entry: str, rounds: int) -> Row:
    """Compare ``entry`` eager versus lazy.

    Args:
        entry: Dotted module path to import.
        rounds: ABBA rounds; each yields two samples per variant.

    Returns:
        A :class:`Row` with medians and a measured (never hardcoded) improvement.
    """
    eager_ms, lazy_ms = abba(
        lambda: float(probe(entry, eager=True)["ms"]),  # type: ignore[arg-type]
        lambda: float(probe(entry, eager=False)["ms"]),  # type: ignore[arg-type]
        rounds,
    )
    eager_med, lazy_med = statistics.median(eager_ms), statistics.median(lazy_ms)
    eager_use, lazy_use = abba(
        lambda: float(probe(entry, eager=True, use=True)["ms"]),  # type: ignore[arg-type]
        lambda: float(probe(entry, eager=False, use=True)["ms"]),  # type: ignore[arg-type]
        rounds,
    )
    eager_use_med, lazy_use_med = statistics.median(eager_use), statistics.median(lazy_use)
    eager_once, lazy_once = probe(entry, eager=True), probe(entry, eager=False)
    return Row(
        entry=entry,
        eager_ms=round(eager_med, 1),
        lazy_ms=round(lazy_med, 1),
        improvement_pct=round((eager_med - lazy_med) / eager_med * 100.0, 1),
        eager_modules=int(eager_once["modules"]),  # type: ignore[call-overload]
        lazy_modules=int(lazy_once["modules"]),  # type: ignore[call-overload]
        eager_tracked=list(eager_once["tracked"]),  # type: ignore[call-overload]
        lazy_tracked=list(lazy_once["tracked"]),  # type: ignore[call-overload]
        eager_first_use_ms=round(eager_use_med, 1),
        lazy_first_use_ms=round(lazy_use_med, 1),
        first_use_improvement_pct=round((eager_use_med - lazy_use_med) / eager_use_med * 100.0, 1),
    )


def main(argv: list[str] | None = None) -> int:
    """Run the benchmark and print a table (or JSON with ``--json``)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rounds", type=int, default=5, help="ABBA rounds per entry point")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    args = parser.parse_args(argv)
    rows = [measure(entry, args.rounds) for entry in ENTRY_POINTS]
    if args.json:
        print(json.dumps([asdict(r) for r in rows], indent=2))
        return 0
    print(
        f"{'entry point':24}{'import: eager':>14}{'lazy':>7}{'gain':>7}"
        f"{'| +first use: eager':>20}{'lazy':>7}{'gain':>7}{'modules':>13}"
    )
    for r in rows:
        print(
            f"{r.entry:24}{r.eager_ms:>14.0f}{r.lazy_ms:>7.0f}{r.improvement_pct:>6.1f}%"
            f"{r.eager_first_use_ms:>20.0f}{r.lazy_first_use_ms:>7.0f}{r.first_use_improvement_pct:>6.1f}%"
            f"{r.eager_modules:>7} ->{r.lazy_modules:>4}"
        )
    mean_import = statistics.mean(r.improvement_pct for r in rows)
    mean_use = statistics.mean(r.first_use_improvement_pct for r in rows)
    print(
        f"mean gain: import {mean_import:.1f}%, import + first use {mean_use:.1f}% | "
        f"{2 * args.rounds} samples per variant | median of ABBA"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
