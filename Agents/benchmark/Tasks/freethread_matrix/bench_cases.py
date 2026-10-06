"""Free-threading benchmark cases. Standard library only, so it runs under any CPython.

Run it inside one interpreter and read JSON on stdout::

    python bench_cases.py --json [--quick]

Cases (each reports measured values, or ``{"skipped": reason}``):

* ``threads_cpu``    pure-Python CPU work spread over 1..N threads: wall time, speedup vs 1 thread.
* ``threads_ast``    parse + walk the repo's own sources with ``ast`` in N threads (the workload of
                     ``swarm_sdk.core.lifeguard_ast``), plus the real auditor when pydantic imports.
* ``lazy_import``    PEP 810 ``lazy import`` vs eager import start-up time (needs CPython 3.15).
* ``sentinel``       PEP 661 ``sentinel`` vs ``object()``: copy/pickle identity, ``is`` cost (3.15).
* ``numba``          can numba be imported here, and if so JIT vs pure Python on a loop.
"""

from __future__ import annotations

import argparse
import ast
import copy
import json
import os
import pickle
import statistics
import subprocess
import sys
import time
import timeit
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
LAZY_MODULES = (
    "asyncio decimal email.message http.client sqlite3 xml.dom.minidom unittest argparse "
    "logging.handlers multiprocessing concurrent.futures ssl zipfile tarfile csv pydoc inspect "
    "dataclasses typing ast tokenize"
).split()


def gil_enabled() -> bool:
    return bool(getattr(sys, "_is_gil_enabled", lambda: True)())


def _fib(n: int) -> int:
    return n if n < 2 else _fib(n - 1) + _fib(n - 2)


def _best(fn, repeat: int) -> float:
    return min(_timed(fn) for _ in range(repeat))


def _timed(fn) -> float:
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start


def _scale(task, items: list, threads: tuple[int, ...], repeat: int) -> dict[str, object]:
    times: dict[str, float] = {}
    for count in threads:

        def run(count: int = count) -> None:
            with ThreadPoolExecutor(max_workers=count) as pool:
                list(pool.map(task, items))

        run()  # warm-up
        times[str(count)] = round(_best(run, repeat), 4)
    base = times[str(threads[0])]
    return {
        "seconds": times,
        "speedup": {k: round(base / v, 2) for k, v in times.items()},
        "efficiency_at_max": round(base / times[str(threads[-1])] / threads[-1], 2),
    }


def case_threads_cpu(quick: bool) -> dict[str, object]:
    n, tasks = (22, 12) if quick else (26, 24)
    return _scale(_fib, [n] * tasks, (1, 2, 4, 6), 1 if quick else 3) | {
        "work": f"fib({n}) x {tasks}"
    }


def _source_files(limit: int) -> list[str]:
    files = sorted((ROOT / "src" / "swarm_sdk").rglob("*.py"))[:limit]
    return [p.read_text(encoding="utf-8", errors="replace") for p in files]


def _walk(source: str) -> int:
    return sum(1 for _ in ast.walk(ast.parse(source)))


def case_threads_ast(quick: bool) -> dict[str, object]:
    sources = _source_files(40 if quick else 400)
    result = _scale(_walk, sources, (1, 2, 4, 6), 1 if quick else 3)
    result["work"] = f"ast.parse+walk of {len(sources)} files"
    sys.path.insert(0, str(ROOT / "src"))
    try:
        from swarm_sdk.core.lifeguard_ast import MetaLifeguardAuditor
    except Exception as exc:  # pydantic (or its compiled core) may be missing for this interpreter
        result["lifeguard_auditor"] = {"skipped": f"{type(exc).__name__}: {str(exc)[:80]}"}
        return result

    def audit(source: str) -> int:
        return len(MetaLifeguardAuditor().audit(source).violations)

    result["lifeguard_auditor"] = _scale(audit, sources[: len(sources) // 2 or 1], (1, 2, 4, 6), 1)
    return result


def _import_cmd(lazy: bool) -> str:
    prefix = "lazy import " if lazy else "import "
    return "\n".join(prefix + name for name in LAZY_MODULES)


def _startup(code: str, runs: int) -> float:
    samples = []
    for _ in range(runs):
        start = time.perf_counter()
        subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)
        samples.append(time.perf_counter() - start)
    return statistics.median(samples)


def case_lazy_import(quick: bool) -> dict[str, object]:
    if sys.version_info < (3, 15):
        return {"skipped": "PEP 810 lazy imports need CPython 3.15"}
    runs = 3 if quick else 9
    try:
        base = _startup("pass", runs)
        eager = _startup(_import_cmd(False), runs)
        lazy = _startup(_import_cmd(True), runs)
    except subprocess.CalledProcessError as exc:
        return {"skipped": f"lazy import failed to run: {exc.stderr.decode()[-120:]}"}
    return {
        "modules": len(LAZY_MODULES),
        "baseline_s": round(base, 4),
        "eager_s": round(eager, 4),
        "lazy_s": round(lazy, 4),
        "saved_ms": round((eager - lazy) * 1000, 1),
        "lazy_overhead_vs_baseline_ms": round((lazy - base) * 1000, 1),
    }


def case_sentinel(quick: bool) -> dict[str, object]:
    import builtins

    sentinel = getattr(builtins, "sentinel", None)
    if sentinel is None:
        return {"skipped": "builtin sentinel needs CPython 3.15 (PEP 661)"}
    missing = sentinel("MISSING")
    plain = object()
    loops = 200_000 if quick else 5_000_000
    return {
        "repr": repr(missing),
        "copy_keeps_identity": {
            "sentinel": copy.copy(missing) is missing,
            "object()": copy.copy(plain) is plain,
        },
        "deepcopy_keeps_identity": {
            "sentinel": copy.deepcopy(missing) is missing,
            "object()": copy.deepcopy(plain) is plain,
        },
        "is_check_ns": {
            "sentinel": round(
                timeit.timeit("x is m", globals={"x": missing, "m": missing}, number=loops)
                / loops
                * 1e9,
                1,
            ),
            "object()": round(
                timeit.timeit("x is m", globals={"x": plain, "m": plain}, number=loops)
                / loops
                * 1e9,
                1,
            ),
        },
        "create_us": {
            "sentinel": round(
                timeit.timeit(lambda: sentinel("X"), number=50_000) / 50_000 * 1e6, 2
            ),
            "object()": round(timeit.timeit(object, number=50_000) / 50_000 * 1e6, 2),
        },
        "pickle_roundtrip_identity": _pickle_identity(missing),
    }


def _pickle_identity(value: object) -> object:
    try:
        return pickle.loads(pickle.dumps(value)) is value
    except Exception as exc:  # unpicklable by reference when it is not a module-level name
        return f"{type(exc).__name__}"


def case_numba(quick: bool) -> dict[str, object]:
    try:
        import numba
    except Exception as exc:
        return {"skipped": f"numba not importable: {type(exc).__name__}: {str(exc)[:80]}"}
    n = 2_000_000 if quick else 20_000_000

    def loop(count: int) -> int:
        total = 0
        for i in range(count):
            total += i % 7
        return total

    jitted = numba.njit(loop)
    jitted(10)  # compile
    return {
        "numba": numba.__version__,
        "python_s": round(_best(lambda: loop(n), 1), 4),
        "numba_s": round(_best(lambda: jitted(n), 3), 5),
    }


CASES = {
    "threads_cpu": case_threads_cpu,
    "threads_ast": case_threads_ast,
    "lazy_import": case_lazy_import,
    "sentinel": case_sentinel,
    "numba": case_numba,
}


def run(selected: list[str] | None = None, quick: bool = False) -> dict[str, Any]:
    report: dict[str, Any] = {
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "gil_enabled": gil_enabled(),
        "cpu_count": os.cpu_count(),
        "loadavg_1m_start": round(os.getloadavg()[0], 2),
        "cases": {},
    }
    for name in selected or list(CASES):
        try:
            report["cases"][name] = CASES[name](quick)
        except Exception as exc:  # one broken case must not hide the others
            report["cases"][name] = {"error": f"{type(exc).__name__}: {str(exc)[:120]}"}
    report["loadavg_1m_end"] = round(os.getloadavg()[0], 2)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--quick", action="store_true", help="tiny sizes: smoke test, not a measurement"
    )
    parser.add_argument("--case", action="append", choices=sorted(CASES))
    args = parser.parse_args()
    report = run(args.case, args.quick)
    print(json.dumps(report, indent=None if args.json else 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
