"""Every Python file under Core must compile on the project's Python (3.15, PEP 810 syntax)."""

from __future__ import annotations

from pathlib import Path

import pytest

CORE = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".pixi", ".venv", "__pycache__", ".remember", "node_modules"}


def python_files(root: Path) -> list[Path]:
    """List Python source files under ``root``, skipping caches and environments."""
    return sorted(
        path
        for path in root.rglob("*.py")
        if not SKIP_DIRS.intersection(path.relative_to(root).parts)
    )


def check_syntax(path: Path) -> None:
    """Compile ``path`` without running it. Raises SyntaxError on invalid source."""
    compile(path.read_text(encoding="utf-8"), str(path), "exec")


def test_check_syntax_rejects_broken_source(tmp_path: Path) -> None:
    broken = tmp_path / "broken.py"
    broken.write_text("def broken(:\n", encoding="utf-8")
    with pytest.raises(SyntaxError):
        check_syntax(broken)


def test_check_syntax_accepts_lazy_import(tmp_path: Path) -> None:
    sample = tmp_path / "lazy_sample.py"
    sample.write_text("lazy import json\n", encoding="utf-8")
    check_syntax(sample)


def test_core_has_python_files() -> None:
    assert python_files(CORE)


@pytest.mark.parametrize("path", python_files(CORE), ids=lambda p: str(p.relative_to(CORE)))
def test_core_file_compiles(path: Path) -> None:
    check_syntax(path)
