"""Measure code-standards coverage of ``src/swarm_sdk`` before and after the standards pass.

The baseline is the real tree at ``BASELINE_REF`` (extracted with ``git archive`` into a
temp dir); the current side is the working tree. Both are audited by the same AST pass:
module docstrings, public-API docstrings, public-API annotations, and the project-mandated
``from __future__ import annotations``. Throughput is the median of several full-tree
audits. ``improvement_pct`` is computed from the measured values, never hardcoded.
"""

from __future__ import annotations

import ast
import statistics
import subprocess
import tarfile
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

#: Last commit before the standards pass (docstrings, future imports, ``ty`` fixes).
BASELINE_REF = "36085aa"

_REPO = Path(__file__).resolve().parents[4]
_PKG = "src/swarm_sdk"
_EXCLUDED = frozenset({"pb", "__pycache__"})
_RUNS = 5


@dataclass(slots=True)
class Tally:
    """Counts of audited items; each ``*_ok`` is a subset of its ``*_total``."""

    files: int = 0
    module_doc_ok: int = 0
    future_ok: int = 0
    pub_total: int = 0
    pub_doc_ok: int = 0
    pub_ann_ok: int = 0


def _is_public(name: str) -> bool:
    """Return whether ``name`` is part of the public API (no leading underscore)."""
    return not name.startswith("_")


def _defs(
    body: list[ast.stmt], in_class: bool = False
) -> Iterator[tuple[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, bool]]:
    """Yield ``(node, is_method)`` for classes and functions reachable without entering defs."""
    for node in body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield node, in_class
        elif isinstance(node, ast.ClassDef):
            yield node, in_class
            yield from _defs(node.body, True)


def _annotated(fn: ast.FunctionDef | ast.AsyncFunctionDef, is_method: bool) -> bool:
    """Return whether every parameter (ignoring self/cls) and the return are annotated."""
    args = fn.args
    params = [*args.posonlyargs, *args.args, *args.kwonlyargs]
    params += [a for a in (args.vararg, args.kwarg) if a is not None]
    if is_method and params and params[0].arg in {"self", "cls"}:
        params = params[1:]
    return all(a.annotation is not None for a in params) and fn.returns is not None


def audit_file(source: str) -> Tally:
    """Audit one module's source text."""
    tree = ast.parse(source)
    t = Tally(files=1)
    body = tree.body
    t.module_doc_ok = int(bool(ast.get_docstring(tree)))
    rest = body[1:] if t.module_doc_ok else body
    first = rest[0] if rest else None
    t.future_ok = int(
        isinstance(first, ast.ImportFrom)
        and first.module == "__future__"
        and any(a.name == "annotations" for a in first.names)
    )
    for node, is_method in _defs(body):
        if not _is_public(node.name):
            continue
        t.pub_total += 1
        t.pub_doc_ok += int(bool(ast.get_docstring(node)))
        if isinstance(node, ast.ClassDef):
            t.pub_ann_ok += 1  # classes carry no signature to annotate
        else:
            t.pub_ann_ok += int(_annotated(node, is_method))
    return t


def audit_tree(root: Path) -> tuple[Tally, float]:
    """Audit every non-generated module under ``root``; return the tally and seconds taken."""
    paths = sorted(p for p in root.rglob("*.py") if not _EXCLUDED & set(p.relative_to(root).parts))
    sources = [p.read_text(encoding="utf-8") for p in paths]  # exclude disk I/O from the timing
    total = Tally()
    start = time.perf_counter()
    for src in sources:
        part = audit_file(src)
        for field in total.__slots__:
            setattr(total, field, getattr(total, field) + getattr(part, field))
    return total, time.perf_counter() - start


def _extract_baseline(dest: Path) -> Path:
    """Materialise ``BASELINE_REF``'s package tree under ``dest`` and return its root."""
    proc = subprocess.run(
        ["git", "archive", "--format=tar", BASELINE_REF, _PKG],
        cwd=_REPO,
        capture_output=True,
        check=True,
        timeout=120,
    )
    archive = dest / "baseline.tar"
    archive.write_bytes(proc.stdout)
    with tarfile.open(archive) as tar:
        # filter="data" rejects absolute paths and unsafe links in the archive (PEP 706).
        tar.extractall(dest, filter="data")
    return dest / _PKG


def _pct(ok: int, total: int) -> float:
    """Return ``ok/total`` as a percentage; an empty population counts as 100%."""
    return ok / total * 100.0 if total else 100.0


def _metric(
    name: str,
    baseline: float,
    current: float,
    *,
    higher_is_better: bool,
    detail: dict[str, Any],
) -> dict[str, Any]:
    """One report row; ``improvement_pct`` needs a non-zero baseline."""
    if baseline:
        improvement = (current - baseline) / baseline * 100.0
        if not higher_is_better:
            improvement = -improvement
    else:
        improvement = float("nan")
    return {
        "name": name,
        "baseline": round(baseline, 4),
        "current": round(current, 4),
        "improvement_pct": round(improvement, 2) if improvement == improvement else None,
        "delta_pp": round(current - baseline, 4),
        "higher_is_better": higher_is_better,
        "detail": detail,
    }


def run() -> dict[str, Any]:
    """Audit the baseline commit and the working tree; return the report dict."""
    with tempfile.TemporaryDirectory() as tmp:
        base_root = _extract_baseline(Path(tmp))
        base, _ = audit_tree(base_root)
        cur, _ = audit_tree(_REPO / _PKG)
        # The first audit above supplies the counts; these repeats only measure throughput.
        base_rates = [audit_tree(base_root)[1] for _ in range(_RUNS)]
        cur_rates = [audit_tree(_REPO / _PKG)[1] for _ in range(_RUNS)]

    rows = (
        (
            "module_docstring_pct",
            _pct(base.module_doc_ok, base.files),
            _pct(cur.module_doc_ok, cur.files),
        ),
        (
            "public_docstring_pct",
            _pct(base.pub_doc_ok, base.pub_total),
            _pct(cur.pub_doc_ok, cur.pub_total),
        ),
        (
            "public_annotation_pct",
            _pct(base.pub_ann_ok, base.pub_total),
            _pct(cur.pub_ann_ok, cur.pub_total),
        ),
        ("future_import_pct", _pct(base.future_ok, base.files), _pct(cur.future_ok, cur.files)),
    )
    metrics = [
        _metric(
            name,
            b,
            c,
            higher_is_better=True,
            detail={"baseline_ref": BASELINE_REF, "files": [base.files, cur.files]},
        )
        for name, b, c in rows
    ]
    metrics.append(
        _metric(
            "audit_files_per_s",
            base.files / statistics.median(base_rates),
            cur.files / statistics.median(cur_rates),
            higher_is_better=True,
            detail={"runs": _RUNS, "note": "audit cost; informational, not a quality gate"},
        )
    )
    measured = [
        cast(float, m["improvement_pct"]) for m in metrics[:4] if m["improvement_pct"] is not None
    ]
    return {
        "baseline_ref": BASELINE_REF,
        "runs": _RUNS,
        "metrics": metrics,
        "mean_improvement_pct": round(statistics.mean(measured), 2) if measured else None,
        "selection": "git-archived baseline tree vs working tree, same AST audit",
    }
