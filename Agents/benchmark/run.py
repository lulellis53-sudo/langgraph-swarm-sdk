"""Run a single benchmark task by name."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a benchmark task")
    parser.add_argument("--task", required=True, help="Task folder name under benchmark/Tasks")
    args = parser.parse_args(argv)

    task_dir = Path(__file__).parent / "Tasks" / args.task
    candidates = list(task_dir.glob("test_*.py"))
    module_path = candidates[0] if candidates else task_dir / "test_benchmark.py"
    if not module_path.is_file():
        print(f"missing {module_path}", file=sys.stderr)
        return 1

    spec = importlib.util.spec_from_file_location(f"bench_{args.task}", module_path)
    if spec is None or spec.loader is None:
        return 1
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if hasattr(module, "run"):
        module.run()
    print(f"OK: {args.task}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
