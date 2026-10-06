"""Run ``bench_cases.py`` under several CPython builds and print one comparison table.

    python Agents/benchmark/Tasks/freethread_matrix/run_matrix.py [--quick] [--out DIR]

Each interpreter runs the cases in its own process. ``PYTHON_GIL=1`` re-enables the GIL on a
free-threaded build, which separates "free-threaded build" from "GIL actually off". The report
carries the 1-minute load average at start and end of every run; when it is high the numbers
are noisy and say so.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
HOME = Path.home()
RESULTS = HERE.parents[1] / "results" / "freethread_matrix"
INTERPRETERS: dict[str, tuple[Path, dict[str, str]]] = {
    "3.14 (GIL)": (HOME / ".local/opt/python-3.14.7/bin/python3", {}),
    "3.14 project venv": (HERE.parents[3] / ".venv/bin/python", {}),  # pydantic: real lifeguard
    "3.14t (no GIL)": (HOME / ".local/bin/python3.14t", {}),
    "3.15 (GIL)": (HOME / ".local/opt/python-3.15-g6413901/bin/python3", {}),
    "3.15t (no GIL)": (HOME / ".local/opt/python-3.15t-g6413901/bin/python3.15t", {}),
    "3.15t, PYTHON_GIL=1": (
        HOME / ".local/opt/python-3.15t-g6413901/bin/python3.15t",
        {"PYTHON_GIL": "1"},
    ),
}


def noisy(rep: dict[str, Any]) -> bool:
    """True when the machine was busier than its core count while the cases ran."""
    cores = os.cpu_count() or 1
    start, end = rep.get("loadavg_1m_start"), rep.get("loadavg_1m_end")
    return not isinstance(start, (int, float)) or max(start, end or 0) > cores


def wait_idle(max_load: float, max_wait_s: float) -> float:
    """Block until the 1-minute load average is <= ``max_load`` or ``max_wait_s`` passes."""
    deadline = time.monotonic() + max_wait_s
    while os.getloadavg()[0] > max_load and time.monotonic() < deadline:
        time.sleep(10)
    return os.getloadavg()[0]


def run_one(
    python: Path, extra_env: dict[str, str], quick: bool, timeout_s: float
) -> dict[str, Any]:
    cmd = [str(python), str(HERE / "bench_cases.py"), "--json", *(["--quick"] if quick else [])]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
        env={**os.environ, **extra_env},
    )
    if proc.returncode != 0:
        return {"error": f"rc={proc.returncode}: {proc.stderr.strip().splitlines()[-1:]}"}
    return json.loads(proc.stdout)


def _fmt(case: dict[str, object] | None, key: str) -> str:
    if not isinstance(case, dict):
        return "-"
    if "skipped" in case or "error" in case:
        return "n/a"
    speedup = case.get("speedup")
    if key == "speedup" and isinstance(speedup, dict):
        return f"{speedup.get('1')}/{speedup.get('2')}/{speedup.get('4')}/{speedup.get('6')}x"
    value = case.get(key)
    return "-" if value is None else str(value)


def table(results: dict[str, dict[str, Any]]) -> str:
    head = "| interpreter | GIL | load start->end | cpu speedup 1/2/4/6 thr "
    head += "| ast speedup 1/2/4/6 thr | lazy saved ms | numba |"
    rows = [head, "|---|---|---|---|---|---|---|"]
    for name, rep in results.items():
        if "error" in rep:
            rows.append(f"| {name} | - | - | {rep['error']} | | | |")
            continue
        cases = rep["cases"]
        gil = "on" if rep["gil_enabled"] else "OFF"
        load = f"{rep['loadavg_1m_start']}->{rep['loadavg_1m_end']}"
        cells = [
            _fmt(cases.get("threads_cpu"), "speedup"),
            _fmt(cases.get("threads_ast"), "speedup"),
            _fmt(cases.get("lazy_import"), "saved_ms"),
            _fmt(cases.get("numba"), "numba"),
        ]
        flag = " **NOISY**" if noisy(rep) else ""
        rows.append(f"| {name} | {gil} | {load}{flag} | " + " | ".join(cells) + " |")
    return "\n".join(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--out", type=Path, default=RESULTS)
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument(
        "--wait-idle",
        type=float,
        metavar="SECONDS",
        default=0,
        help="before each interpreter wait up to SECONDS for load <= half the cores",
    )
    args = parser.parse_args()
    results: dict[str, dict[str, Any]] = {}
    for name, (python, env) in INTERPRETERS.items():
        if not python.exists():
            results[name] = {"error": f"{python} not found"}
            continue
        if args.wait_idle:
            load = wait_idle((os.cpu_count() or 1) / 2, args.wait_idle)
            print(f"load before {name}: {load:.1f}", file=sys.stderr, flush=True)
        print(f"running {name} ...", file=sys.stderr, flush=True)
        results[name] = run_one(python, env, args.quick, args.timeout)
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"{int(time.time())}.json"
    path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(table(results))
    note = "Rows marked NOISY ran while load exceeded the core count: do not trust their ratios."
    print(f"\ncores: {os.cpu_count()}; raw results: {path}\n{note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
