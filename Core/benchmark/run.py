"""Run Core benchmark tasks: ``python -m Core.benchmark.run --task <name>``."""

from __future__ import annotations

import argparse
import importlib
import sys
from typing import Protocol

from Core.benchmark.protocol import BenchmarkResult


class _TaskRunner(Protocol):
    def __call__(self) -> BenchmarkResult: ...


_TASK_MODULES: dict[str, str] = {
    "orchestration_graph": "Core.benchmark.tasks.orchestration_graph.benchmark_orchestration_graph",
    "jev_agent_routing": "Core.benchmark.tasks.jev_agent_routing.benchmark_jev_agent_routing",
}

_ALL_TASKS = tuple(sorted(_TASK_MODULES))


def _load_runner(task: str) -> _TaskRunner:
    module_path = _TASK_MODULES.get(task)
    if module_path is None:
        known = ", ".join(sorted(_TASK_MODULES))
        raise SystemExit(f"Unknown task '{task}'. Known tasks: {known}")
    module = importlib.import_module(module_path)
    runner = getattr(module, "run_benchmark", None)
    if runner is None or not callable(runner):
        raise SystemExit(f"Task module {module_path} has no run_benchmark()")
    return runner


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a Core benchmark task.")
    parser.add_argument(
        "--task",
        required=True,
        help=f"Task name or 'all' ({', '.join(_ALL_TASKS)})",
    )
    args = parser.parse_args(argv)
    tasks = _ALL_TASKS if args.task == "all" else (args.task,)
    if args.task != "all" and args.task not in _TASK_MODULES:
        known = ", ".join((*_ALL_TASKS, "all"))
        raise SystemExit(f"Unknown task '{args.task}'. Known tasks: {known}")

    exit_code = 0
    for task in tasks:
        result = _load_runner(task)()
        status = "PASS" if result.passed else "FAIL"
        extra = ""
        if result.accuracy is not None:
            extra = f" accuracy={result.accuracy:.2%}"
        if result.p95_ms is not None:
            extra += f" p95_ms={result.p95_ms:.2f}"
        print(f"{status} {result.name} p50_ms={result.p50_ms:.2f}{extra}")
        if not result.passed:
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
