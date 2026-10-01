"""AST validation: syntax, public docstrings, and type annotations.

Run: ``uv run python scripts/validate_ast.py``
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".venv", "docs", "scripts"}
SKIP_FILES = {"conftest.py"}


@dataclass(frozen=True, slots=True)
class Issue:
    path: Path
    line: int
    code: str
    message: str


def _py_files() -> list[Path]:
    out: list[Path] = []
    for path in sorted(ROOT.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.name in SKIP_FILES:
            continue
        out.append(path)
    return out


def _is_public(name: str) -> bool:
    return not name.startswith("_")


def _has_docstring(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> bool:
    doc = ast.get_docstring(node, clean=False)
    return bool(doc and doc.strip())


def _annotation_ok(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    missing: list[str] = []
    if fn.returns is None and fn.name != "__init__":
        missing.append("return")
    for arg in fn.args.posonlyargs + fn.args.args:
        if arg.arg in {"self", "cls"}:
            continue
        if arg.annotation is None:
            missing.append(arg.arg)
    if fn.args.vararg and fn.args.vararg.annotation is None:
        missing.append(f"*{fn.args.vararg.arg}")
    if fn.args.kwarg and fn.args.kwarg.annotation is None:
        missing.append(f"**{fn.args.kwarg.arg}")
    return missing


def _check_file(path: Path) -> list[Issue]:
    rel = path.relative_to(ROOT)
    in_tests = "tests" in rel.parts
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [
            Issue(
                path=rel,
                line=exc.lineno or 1,
                code="syntax",
                message=str(exc.msg),
            )
        ]

    issues: list[Issue] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            stack: list[ast.AST] = [node]
            _walk_public_defs(stack, rel, in_tests, issues)
    return issues


def _walk_public_defs(
    stack: list[ast.AST],
    rel: Path,
    in_tests: bool,
    issues: list[Issue],
) -> None:
    while stack:
        node = stack.pop()
        if isinstance(node, ast.ClassDef):
            if not in_tests and _is_public(node.name) and not _has_docstring(node):
                issues.append(
                    Issue(
                        path=rel,
                        line=node.lineno,
                        code="docstring",
                        message=f"public class `{node.name}` missing docstring",
                    )
                )
            protocol = any(
                (isinstance(base, ast.Name) and base.id == "Protocol")
                or (isinstance(base, ast.Attribute) and base.attr == "Protocol")
                for base in node.bases
            )
            for child in node.body:
                if protocol and isinstance(
                    child, (ast.FunctionDef, ast.AsyncFunctionDef)
                ):
                    continue
                stack.append(child)
            continue
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if any(
            isinstance(dec, ast.Name) and dec.id == "overload"
            for dec in node.decorator_list
        ):
            continue
        if in_tests or not _is_public(node.name):
            continue
        if not _has_docstring(node):
            issues.append(
                Issue(
                    path=rel,
                    line=node.lineno,
                    code="docstring",
                    message=f"public function `{node.name}` missing docstring",
                )
            )
        missing = _annotation_ok(node)
        if missing:
            issues.append(
                Issue(
                    path=rel,
                    line=node.lineno,
                    code="annotation",
                    message=(
                        f"public function `{node.name}` missing annotations: "
                        f"{', '.join(missing)}"
                    ),
                )
            )


def main() -> int:
    issues: list[Issue] = []
    for path in _py_files():
        issues.extend(_check_file(path))
    if not issues:
        print(f"validate_ast: OK ({len(_py_files())} files)")
        return 0
    for item in issues:
        print(f"{item.path}:{item.line}: {item.code}: {item.message}")
    print(f"validate_ast: {len(issues)} issue(s)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
