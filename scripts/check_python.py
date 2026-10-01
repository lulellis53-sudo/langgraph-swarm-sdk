"""Run AST, Ruff, and ty checks over project Python sources."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(label: str, cmd: list[str]) -> int:
    print(f"=== {label} ===")
    result = subprocess.run(cmd, cwd=ROOT, check=False)
    return result.returncode


def main() -> int:
    """Execute the full Python quality gate."""
    steps = [
        ("compileall (AST parse)", [sys.executable, "-m", "compileall", "-q", "."]),
        ("validate_ast", [sys.executable, str(ROOT / "scripts" / "validate_ast.py")]),
        ("ruff", [sys.executable, "-m", "ruff", "check", "."]),
        ("ty", [sys.executable, "-m", "ty", "check", "."]),
    ]
    code = 0
    for label, cmd in steps:
        code = _run(label, cmd) or code
    return code


if __name__ == "__main__":
    raise SystemExit(main())
