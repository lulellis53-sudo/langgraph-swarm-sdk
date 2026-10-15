"""Compare SQLite and optional DuckDB for persistent response-cache workloads."""

from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

_ROWS = (100, 1_000, 10_000)
_ROUNDS = 7
_ITERATIONS = 200


def _peak_rss_bytes() -> int:
    """Return process peak RSS in bytes on macOS and Linux."""
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def _percentile(values: list[float], percentile: float) -> float:
    """Return a nearest-rank percentile from sorted millisecond samples."""
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * percentile + 0.999999)))
    return ordered[index]


def _open_database(engine: str, path: Path) -> Any:
    """Open a cache database and create equivalent exact and semantic tables."""
    if engine == "sqlite":
        import sqlite3

        connection = sqlite3.connect(path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            "CREATE TABLE exact_cache ("
            "key TEXT PRIMARY KEY, response TEXT NOT NULL, tenant_id TEXT NOT NULL, "
            "inserted_at INTEGER NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE semantic_cache ("
            "id INTEGER PRIMARY KEY, query_text TEXT NOT NULL, vector BLOB NOT NULL, "
            "response TEXT NOT NULL, tenant_id TEXT NOT NULL, inserted_at INTEGER NOT NULL, "
            "accessed_at INTEGER NOT NULL)"
        )
        return connection
    duckdb = __import__("duckdb")

    connection = duckdb.connect(str(path))
    connection.execute(
        "CREATE TABLE exact_cache ("
        "key VARCHAR PRIMARY KEY, response VARCHAR NOT NULL, tenant_id VARCHAR NOT NULL, "
        "inserted_at BIGINT NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE semantic_cache ("
        "id BIGINT PRIMARY KEY, query_text VARCHAR NOT NULL, vector BLOB NOT NULL, "
        "response VARCHAR NOT NULL, tenant_id VARCHAR NOT NULL, inserted_at BIGINT NOT NULL, "
        "accessed_at BIGINT NOT NULL)"
    )
    return connection


def _worker(engine: str, rows: int, rounds: int, iterations: int, directory: str) -> dict[str, Any]:
    """Run one backend workload in an isolated process and report resources."""
    path = Path(directory) / f"{engine}.db"
    connection = _open_database(engine, path)
    payload = bytes(range(128))
    exact_rows = [(f"key-{i}", f"response-{i}", "default", i) for i in range(rows)]
    semantic_rows = [
        (i + 1, f"query-{i}", payload, f"response-{i}", "default", i, i) for i in range(rows)
    ]
    if engine == "sqlite":
        connection.executemany("INSERT INTO exact_cache VALUES (?, ?, ?, ?)", exact_rows)
        connection.executemany(
            "INSERT INTO semantic_cache VALUES (?, ?, ?, ?, ?, ?, ?)", semantic_rows
        )
        connection.commit()
    else:
        connection.executemany("INSERT INTO exact_cache VALUES (?, ?, ?, ?)", exact_rows)
        connection.executemany(
            "INSERT INTO semantic_cache VALUES (?, ?, ?, ?, ?, ?, ?)", semantic_rows
        )
    target = rows - 1
    operations = {
        "exact_hit": lambda: connection.execute(
            "SELECT response FROM exact_cache WHERE key = ? AND tenant_id = ?",
            (f"key-{target}", "default"),
        ).fetchone(),
        "exact_miss": lambda: connection.execute(
            "SELECT response FROM exact_cache WHERE key = ? AND tenant_id = ?",
            ("missing", "default"),
        ).fetchone(),
        "semantic_scan": lambda: connection.execute(
            "SELECT id, vector, response FROM semantic_cache "
            "WHERE tenant_id = ? ORDER BY id DESC LIMIT 256",
            ("default",),
        ).fetchall(),
        "insert": lambda: connection.execute(
            "INSERT OR REPLACE INTO exact_cache VALUES (?, ?, ?, ?)",
            ("write-key", "write-response", "default", rows + 1),
        ),
    }
    timings: dict[str, dict[str, float]] = {}
    cpu_ms: dict[str, float] = {}
    for name, operation in operations.items():
        samples: list[float] = []
        cpu_started = time.process_time()
        for _ in range(rounds):
            started = time.perf_counter_ns()
            for _ in range(iterations):
                operation()
            samples.append((time.perf_counter_ns() - started) / iterations / 1_000_000)
        cpu_ms[name] = (time.process_time() - cpu_started) * 1000
        timings[name] = {
            "p50_ms": statistics.median(samples),
            "p95_ms": _percentile(samples, 0.95),
            "p99_ms": _percentile(samples, 0.99),
        }
    connection.close()
    return {
        "engine": engine,
        "rows": rows,
        "timings": timings,
        "cpu_ms": cpu_ms,
        "peak_rss_bytes": _peak_rss_bytes(),
        "database_bytes": path.stat().st_size if path.exists() else 0,
    }


def run(
    *,
    sizes: tuple[int, ...] = _ROWS,
    rounds: int = _ROUNDS,
    iterations: int = _ITERATIONS,
) -> dict[str, Any]:
    """Run each available storage backend in fresh subprocesses for clean RSS."""
    if not sizes or any(size < 1 for size in sizes) or rounds < 1 or iterations < 1:
        raise ValueError("sizes, rounds, and iterations must be positive")
    engines = ["sqlite"]
    if importlib.util.find_spec("duckdb") is None:
        unavailable = ["duckdb"]
    else:
        engines.append("duckdb")
        unavailable = []
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="swarm-cache-storage-") as directory:
        for size in sizes:
            for engine in engines:
                engine_directory = Path(directory) / f"{engine}-{size}"
                engine_directory.mkdir()
                command = [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--worker",
                    engine,
                    str(size),
                    str(rounds),
                    str(iterations),
                    str(engine_directory),
                ]
                completed = subprocess.run(command, check=True, capture_output=True, text=True)
                results.append(json.loads(completed.stdout))
    return {
        "metadata": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "sizes": list(sizes),
            "rounds": rounds,
            "iterations_per_round": iterations,
            "isolated_process_per_engine_and_size": True,
            "unavailable_engines": unavailable,
        },
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    """Run the cache storage benchmark or its private worker process."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+", default=list(_ROWS))
    parser.add_argument("--rounds", type=int, default=_ROUNDS)
    parser.add_argument("--iterations", type=int, default=_ITERATIONS)
    parser.add_argument("--worker", choices=("sqlite", "duckdb"))
    parser.add_argument("_worker_rows", type=int, nargs="?")
    parser.add_argument("_worker_rounds", type=int, nargs="?")
    parser.add_argument("_worker_iterations", type=int, nargs="?")
    parser.add_argument("_worker_directory", nargs="?")
    args = parser.parse_args(argv)
    if args.worker:
        report = _worker(
            args.worker,
            args._worker_rows,
            args._worker_rounds,
            args._worker_iterations,
            args._worker_directory,
        )
    else:
        report = run(sizes=tuple(args.sizes), rounds=args.rounds, iterations=args.iterations)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
