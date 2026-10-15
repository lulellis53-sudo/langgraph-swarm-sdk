# Merge small `swarm_sdk` folders (A–D) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge `server`→`serving`, `execution`+`observability`→`runtime`, `prompting`→`models`, `math`+`gpu`→`compute` under `src/swarm_sdk/` with no behavior change.

**Architecture:** Move files with `git mv`, rewrite every importer and path reference with one mapping-driven script, delete the emptied folders, and pin the new layout with a test. One merge per task; each task ends with the full gate so any task can be the last one shipped.

**Tech Stack:** Python 3.14, uv, pytest, ruff, ty, git. Working directory for every command: `/Users/usuario/Swarm/WebSearch`.

**Spec:** `docs/superpowers/specs/2026-10-06-merge-folders-design.md`

## Global Constraints

- No behavior or signature changes; no compatibility shims; `vault.py`, `pb/`, `swarm_sdk/__init__.py` exports untouched.
- Merge E (`memory` → `retrieval`) is out of scope.
- Historic records under `docs/superpowers/` keep their old paths (the rewrite script skips that folder).
- Commit only if the user asked. Commit steps below are marked "(only if the user asked)"; otherwise skip them. Another process auto-commits this worktree, so keep each task's edits and gate inside one working session.
- Tests run only with this exact command (root `__init__.py` breaks default collection). It is called `PYTEST` below:
  `uv run --extra dev --extra faiss --extra pydantic-ai --extra observability pytest -c /dev/null --rootdir=tests -o asyncio_mode=auto tests -q --tb=no -p no:cacheprovider --continue-on-collection-errors`
- Baseline the gate must never fall below: `4 failed, 485 passed, 1 error` (failures: `test_spawn_orchestrator.py` x2, `test_vault_keys.py` x2; error: `tests/test_autonomous.py`).
- `uv run ty check src` diagnostics must stay at or below 15; `uv run ruff check src tests` clean for touched files.
- Cold import `python -X importtime -c "import swarm_sdk.core.swarm"` stays at about 0.46 s (0.43–0.49 measured); a clear regression above 0.55 s is a failure.

## Review Focus

- A leftover `__pycache__` in an emptied folder keeps `import swarm_sdk.<old>` working as a namespace package, hiding a missed rewrite → test asserts old packages are gone (`ModuleNotFoundError`).
- String-based references the AST/import sweep cannot see (`monkeypatch.setattr("swarm_sdk.x.y", ...)`, `langgraph.json`, `pyproject.toml` ruff path ignores, docs) → final `rg` sweep plus the layout test.
- Eager `__init__` imports pulling heavy modules into previously light paths (`compute/__init__` for `scoring`, `runtime/__init__` for `usage`) → import-time gate and an import-all-modules check.
- Import cycles created by merging (`core`↔`serving`, `models`↔`runtime`) → import-all-modules check imports every module in a fresh interpreter.
- The LangGraph factory path (`langgraph.json`) must load by file path → smoke import of `src/swarm_sdk/serving/graphs.py` via `importlib`.

---

## File Structure

| Path | Responsibility |
|---|---|
| `scratch/merge_tools/rewrite.py` (new, untracked scratch) | Mapping-driven rewrite of dotted and slash paths across the repo |
| `scratch/merge_tools/check_imports.py` (new, untracked scratch) | Import every `swarm_sdk` module in a fresh interpreter, fail on `swarm_sdk` import errors |
| `tests/test_package_layout.py` (new) | Pins the new layout and that old packages no longer import |
| `src/swarm_sdk/serving/graphs.py` | Was `server/graphs.py` |
| `src/swarm_sdk/runtime/{__init__,concurrency,executor,fanout,metrics,tracing,usage}.py` | Was `execution/*` + `observability/*` |
| `src/swarm_sdk/models/budget.py` | Was `prompting/budget.py` |
| `src/swarm_sdk/compute/{__init__,lazy_dispatcher,opencl_math,report,scoring}.py` | Was `gpu/*` + `math/__init__.py` (as `scoring.py`) |

---

### Task 0: Safety net, tooling, baseline

**Files:**
- Create: `scratch/merge_tools/rewrite.py`, `scratch/merge_tools/check_imports.py`, `tests/test_package_layout.py`
- Backup (outside repo): scratchpad tarball

**Interfaces:**
- Produces: `rewrite.py MAP... ` where each `MAP` is `old=new` dotted module prefixes; rewrites dotted (`swarm_sdk.old`) and slash (`swarm_sdk/old`) forms in all text files except `.git`, `.venv`, `uv.lock`, `__pycache__`, `docs/superpowers`, `scratch/merge_tools`; prints changed files; `--dry-run` lists without writing. `check_imports.py` exits 1 if any module fails with a message mentioning `swarm_sdk`.
- Produces: `tests/test_package_layout.py` with `REMOVED: list[str]` and `PRESENT: list[str]` module lists that later tasks extend.

- [ ] **Step 1: Back up and record the baseline**

```bash
S=/private/tmp/claude-501/-Users-usuario-Swarm-WebSearch/48dbcba7-1169-423b-88a5-3e656fc8d789/scratchpad
tar -czf $S/merge-before.tgz src tests langgraph.json pyproject.toml AGENTS.md README.md Toolchain.md docs/Molten.md WebSearch
uv run --extra dev --extra faiss --extra pydantic-ai --extra observability pytest -c /dev/null --rootdir=tests -o asyncio_mode=auto tests -q --tb=no -p no:cacheprovider --continue-on-collection-errors 2>&1 | tail -3
uv run --extra dev --extra observability ty check src 2>&1 | rg -c "^(error|warning)"
```
Expected: tarball created; `4 failed, 485 passed, 1 error` (or better); ty count `15`.

- [ ] **Step 2: Write `scratch/merge_tools/rewrite.py`**

```python
"""Rewrite swarm_sdk module paths. Usage: rewrite.py [--dry-run] old=new [old=new ...]

`old`/`new` are dotted prefixes, e.g. swarm_sdk.execution=swarm_sdk.runtime.
Both `swarm_sdk.a.b` and `swarm_sdk/a/b` spellings are rewritten.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SKIP_DIRS = {".git", ".venv", "__pycache__", ".ruff_cache", ".pytest_cache", "target", "node_modules"}
SKIP_PREFIXES = ("docs/superpowers", "scratch/merge_tools", "tests/test_package_layout.py")
SKIP_NAMES = {"uv.lock"}
TEXT_SUFFIXES = {".py", ".md", ".mdc", ".toml", ".json", ".yaml", ".yml", ".txt", ".cfg", ".sh"}


def build_patterns(pairs: list[tuple[str, str]]) -> list[tuple[re.Pattern[str], str]]:
    patterns: list[tuple[re.Pattern[str], str]] = []
    for old, new in pairs:
        # Not followed by an identifier char, so `swarm_sdk.math` never matches `swarm_sdk.mathx`.
        patterns.append((re.compile(re.escape(old) + r"(?![A-Za-z0-9_])"), new))
        old_slash, new_slash = old.replace(".", "/"), new.replace(".", "/")
        patterns.append((re.compile(re.escape(old_slash) + r"(?![A-Za-z0-9_])"), new_slash))
    return patterns


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    pairs = [(a.split("=", 1)[0], a.split("=", 1)[1]) for a in argv if "=" in a]
    if not pairs:
        print(__doc__)
        return 2
    patterns = build_patterns(pairs)
    root = Path.cwd()
    changed = 0
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if (
            not path.is_file()
            or path.suffix not in TEXT_SUFFIXES
            or path.name in SKIP_NAMES
            or any(part in SKIP_DIRS for part in rel.parts)
            or str(rel).startswith(SKIP_PREFIXES)
        ):
            continue
        text = path.read_text(encoding="utf-8")
        new_text = text
        for pattern, replacement in patterns:
            new_text = pattern.sub(replacement, new_text)
        if new_text != text:
            changed += 1
            print(rel)
            if not dry:
                path.write_text(new_text, encoding="utf-8")
    print(f"{changed} file(s) {'would change' if dry else 'changed'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 3: Write `scratch/merge_tools/check_imports.py`**

```python
"""Import every swarm_sdk module in a fresh interpreter; fail on swarm_sdk-related errors."""

from __future__ import annotations

import importlib
import pkgutil
import sys

import swarm_sdk

failures: list[str] = []
for info in pkgutil.walk_packages(swarm_sdk.__path__, "swarm_sdk."):
    try:
        importlib.import_module(info.name)
    except ImportError as exc:  # optional third-party deps are tolerated
        if "swarm_sdk" in str(exc):
            failures.append(f"{info.name}: {exc}")
    except Exception as exc:  # report any import-time crash, not only ImportError
        failures.append(f"{info.name}: {type(exc).__name__}: {exc}")
for line in failures:
    print(line, file=sys.stderr)
print(f"{len(failures)} failing module(s)")
sys.exit(1 if failures else 0)
```

- [ ] **Step 4: Write `tests/test_package_layout.py`**

```python
"""Pins the merged package layout: new modules import, old packages are gone."""

from __future__ import annotations

import importlib

import pytest

REMOVED: list[str] = []
PRESENT: list[str] = []


@pytest.mark.parametrize("name", REMOVED)
def test_old_package_is_gone(name: str) -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(name)


@pytest.mark.parametrize("name", PRESENT)
def test_new_module_imports(name: str) -> None:
    importlib.import_module(name)
```

- [ ] **Step 5: Verify the tooling**

Run: `uv run python scratch/merge_tools/check_imports.py; echo exit=$?` and `uv run python scratch/merge_tools/rewrite.py --dry-run swarm_sdk.server=swarm_sdk.serving`
Expected: check_imports prints `0 failing module(s)`, `exit=0` (optional deps like `redis`, `pyarrow` raise ImportError without `swarm_sdk` in the message and are tolerated); the dry run lists `AGENTS.md`, `README.md`, `langgraph.json`, `src/swarm_sdk/server/...` and writes nothing (`git status --short` unchanged apart from the new files).

- [ ] **Step 6: Commit (only if the user asked)**

```bash
git add tests/test_package_layout.py
git commit -m "test: add package layout pin for folder merges"
```

---

### Task 1: Merge A — `server` into `serving`

**Files:**
- Move: `src/swarm_sdk/server/graphs.py` → `src/swarm_sdk/serving/graphs.py`
- Delete: `src/swarm_sdk/server/` (including `__init__.py`, `__pycache__`)
- Modify (via script): `langgraph.json`, `AGENTS.md`, `README.md`
- Modify: `tests/test_package_layout.py`

**Interfaces:**
- Consumes: Task 0 tools and `REMOVED`/`PRESENT` lists.
- Produces: module `swarm_sdk.serving.graphs` exposing `swarm_graph`, `plan_graph` (names unchanged); `swarm_sdk.server` no longer importable.

- [ ] **Step 1: Write the failing layout test**

In `tests/test_package_layout.py` set:
```python
REMOVED: list[str] = ["swarm_sdk.server"]
PRESENT: list[str] = ["swarm_sdk.serving.graphs"]
```
Run: `uv run --extra dev pytest -c /dev/null --rootdir=tests -o asyncio_mode=auto tests/test_package_layout.py -q --tb=line -p no:cacheprovider`
Expected: FAIL (`swarm_sdk.server` still imports; `swarm_sdk.serving.graphs` missing).

- [ ] **Step 2: Move the file and drop the package**

```bash
git mv src/swarm_sdk/server/graphs.py src/swarm_sdk/serving/graphs.py
git rm -q src/swarm_sdk/server/__init__.py
command rm -rf src/swarm_sdk/server
```
(`command rm -rf` removes the emptied folder and its `__pycache__`, bypassing this shell's `rm` alias; confirm with `ls src/swarm_sdk/server` → "No such file or directory".)

- [ ] **Step 3: Rewrite references**

```bash
uv run python scratch/merge_tools/rewrite.py swarm_sdk.server=swarm_sdk.serving
```
Expected output lists `AGENTS.md`, `README.md`, `langgraph.json` (and nothing under `src/` since only `server/` itself imported it). Then check `langgraph.json` manually:
`rg -n "graphs.py" langgraph.json` → `./src/swarm_sdk/serving/graphs.py:swarm_graph` and `...:plan_graph`.

- [ ] **Step 4: Run the layout test and the gate**

Run the Step 1 command → PASS. Then:
```bash
uv run python scratch/merge_tools/check_imports.py
uv run python - <<'EOF'
import importlib.util, pathlib
p = pathlib.Path("src/swarm_sdk/serving/graphs.py")
spec = importlib.util.spec_from_file_location("graphs_by_path", p)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(callable(m.swarm_graph), callable(m.plan_graph))
EOF
```
Expected: `0 failing module(s)`; `True True`. Then the full gate (see Task 5, Step 1) must show `4 failed, 485+ passed, 1 error`.

- [ ] **Step 5: Commit (only if the user asked)**

```bash
git add -A src/swarm_sdk/serving src/swarm_sdk/server langgraph.json AGENTS.md README.md tests/test_package_layout.py
git commit -m "refactor: merge server into serving"
```

---

### Task 2: Merge B — `execution` + `observability` into `runtime`

**Files:**
- Create: `src/swarm_sdk/runtime/__init__.py`
- Move: `execution/{concurrency,executor,fanout}.py` and `observability/{metrics,tracing,usage}.py` → `src/swarm_sdk/runtime/`
- Delete: `src/swarm_sdk/execution/`, `src/swarm_sdk/observability/`
- Modify (via script): importers in `src/`, `tests/`, docs (`AGENTS.md`, `Toolchain.md`), including `decorators.py`, `core/swarm.py`, `gpu/report.py`, `models/chat.py`, `orchestrator/{graph,spawn}.py`, `serving/{grpc,http}.py`, `tests/test_decorators.py`, `tests/test_static_templates.py`
- Modify: `tests/test_package_layout.py`

**Interfaces:**
- Consumes: Task 0 tools.
- Produces: `swarm_sdk.runtime` exporting `HandoffPayload, SpecialistResult, UsageLog, fan_out, gil_enabled, install_uvloop, offload, parallel_cap`; submodules `swarm_sdk.runtime.{concurrency,executor,fanout,metrics,tracing,usage}`.

- [ ] **Step 1: Write the failing layout test**

Extend the lists:
```python
REMOVED: list[str] = ["swarm_sdk.server", "swarm_sdk.execution", "swarm_sdk.observability"]
PRESENT: list[str] = [
    "swarm_sdk.serving.graphs",
    "swarm_sdk.runtime",
    "swarm_sdk.runtime.concurrency",
    "swarm_sdk.runtime.executor",
    "swarm_sdk.runtime.fanout",
    "swarm_sdk.runtime.metrics",
    "swarm_sdk.runtime.usage",
]
```
Run the layout test → FAIL (new modules missing).

- [ ] **Step 2: Move files and write `runtime/__init__.py`**

```bash
mkdir -p src/swarm_sdk/runtime
git mv src/swarm_sdk/execution/concurrency.py src/swarm_sdk/execution/executor.py src/swarm_sdk/execution/fanout.py src/swarm_sdk/runtime/
git mv src/swarm_sdk/observability/metrics.py src/swarm_sdk/observability/tracing.py src/swarm_sdk/observability/usage.py src/swarm_sdk/runtime/
git rm -q src/swarm_sdk/execution/__init__.py src/swarm_sdk/observability/__init__.py
command rm -rf src/swarm_sdk/execution src/swarm_sdk/observability
```
Create `src/swarm_sdk/runtime/__init__.py`:
```python
"""Runtime plumbing: event-loop offloading, parallel fan-out, metrics and usage tracking."""

from swarm_sdk.runtime.concurrency import gil_enabled, parallel_cap
from swarm_sdk.runtime.executor import install_uvloop, offload
from swarm_sdk.runtime.fanout import HandoffPayload, SpecialistResult, fan_out
from swarm_sdk.runtime.usage import UsageLog

__all__ = [
    "HandoffPayload",
    "SpecialistResult",
    "UsageLog",
    "fan_out",
    "gil_enabled",
    "install_uvloop",
    "offload",
    "parallel_cap",
]
```

- [ ] **Step 3: Rewrite references**

```bash
uv run python scratch/merge_tools/rewrite.py swarm_sdk.execution=swarm_sdk.runtime swarm_sdk.observability=swarm_sdk.runtime
```
Expected: the importers listed under Files. This turns `from swarm_sdk.observability import metrics` into `from swarm_sdk.runtime import metrics` (valid: `metrics` is a submodule). Also the stale `swarm_sdk.runtime` docstring text in `orchestrator/graph.py` becomes true; leave it.
Check no old spelling remains: `rg -n "swarm_sdk[./](execution|observability)" . --glob '!docs/superpowers/**' --glob '!.venv' --glob '!uv.lock' --glob '!scratch/merge_tools/**'` → no output.

- [ ] **Step 4: Run the layout test, import sweep and the gate**

```bash
uv run --extra dev pytest -c /dev/null --rootdir=tests -o asyncio_mode=auto tests/test_package_layout.py tests/test_decorators.py tests/test_static_templates.py -q --tb=short -p no:cacheprovider
uv run python scratch/merge_tools/check_imports.py
```
Expected: all pass, `0 failing module(s)`. Then the full gate (Task 5, Step 1) with baseline numbers. Also run `python -X importtime -c "import swarm_sdk.core.swarm"` 3 times (see Global Constraints).

- [ ] **Step 5: Commit (only if the user asked)**

```bash
git add -A src/swarm_sdk tests AGENTS.md Toolchain.md
git commit -m "refactor: merge execution and observability into runtime"
```

---

### Task 3: Merge C — `prompting` into `models`

**Files:**
- Move: `src/swarm_sdk/prompting/budget.py` → `src/swarm_sdk/models/budget.py`
- Delete: `src/swarm_sdk/prompting/`
- Modify (via script): `core/swarm.py`, `models/chat.py`, `orchestrator/worker.py`
- Modify: `tests/test_package_layout.py`

**Interfaces:**
- Produces: `swarm_sdk.models.budget` exposing `PackedPrompt`, `TokenBudget`, `count_text` (unchanged). `models/__init__.py` is NOT changed (no re-export; every importer uses the module path).

- [ ] **Step 1: Write the failing layout test**

Append `"swarm_sdk.prompting"` to `REMOVED` and `"swarm_sdk.models.budget"` to `PRESENT`; run the layout test → FAIL.

- [ ] **Step 2: Move and clean**

```bash
git mv src/swarm_sdk/prompting/budget.py src/swarm_sdk/models/budget.py
git rm -q src/swarm_sdk/prompting/__init__.py
command rm -rf src/swarm_sdk/prompting
```

- [ ] **Step 3: Rewrite references and check for package-level imports**

```bash
rg -n "swarm_sdk\.prompting import|from swarm_sdk import prompting" src tests WebSearch
uv run python scratch/merge_tools/rewrite.py swarm_sdk.prompting=swarm_sdk.models
```
Expected: the `rg` prints nothing (all importers use `swarm_sdk.prompting.budget`); the script rewrites to `swarm_sdk.models.budget`. If the `rg` prints anything, add that name to `models/__init__.py` explicitly before continuing.

- [ ] **Step 4: Gate**

Layout test PASS; `uv run python scratch/merge_tools/check_imports.py` → `0 failing module(s)`; full gate (Task 5, Step 1); import time within the Global Constraints.

- [ ] **Step 5: Commit (only if the user asked)**

```bash
git add -A src/swarm_sdk tests
git commit -m "refactor: merge prompting into models"
```

---

### Task 4: Merge D — `math` + `gpu` into `compute`

**Files:**
- Create: `src/swarm_sdk/compute/` (via moves)
- Move: `gpu/{__init__,lazy_dispatcher,opencl_math,report}.py` → `compute/`; `math/__init__.py` → `compute/scoring.py`
- Delete: `src/swarm_sdk/gpu/`, `src/swarm_sdk/math/`
- Modify (via script): `pyproject.toml` (ruff per-file ignore `src/swarm_sdk/gpu/opencl_math.py`), `README.md`, `docs/Molten.md`, `core/swarm.py`, `memory/{opencl_store,sqlite_vec}.py`, `retrieval/{cache,embeddings,hybrid,rerank}.py`, `tests/test_lazy_dispatcher.py`, `tests/test_decorators.py`
- Modify: `tests/test_package_layout.py`

**Interfaces:**
- Produces: `swarm_sdk.compute` (the former `swarm_sdk.gpu` API, unchanged names), `swarm_sdk.compute.{lazy_dispatcher,opencl_math,report}`, and `swarm_sdk.compute.scoring` (the former `swarm_sdk.math`: `bm25_*`, `cosine_similarity`, `rrf_score`, `softmax_scores`, `l2_norm`, ...). `scoring` is NOT re-exported from `compute/__init__.py` because `l2_norm` exists in both.

- [ ] **Step 1: Write the failing layout test**

Append `"swarm_sdk.gpu"`, `"swarm_sdk.math"` to `REMOVED`; append `"swarm_sdk.compute"`, `"swarm_sdk.compute.scoring"`, `"swarm_sdk.compute.lazy_dispatcher"`, `"swarm_sdk.compute.opencl_math"`, `"swarm_sdk.compute.report"` to `PRESENT`. Run → FAIL.

- [ ] **Step 2: Move and clean**

```bash
mkdir -p src/swarm_sdk/compute
git mv src/swarm_sdk/gpu/__init__.py src/swarm_sdk/gpu/lazy_dispatcher.py src/swarm_sdk/gpu/opencl_math.py src/swarm_sdk/gpu/report.py src/swarm_sdk/compute/
git mv src/swarm_sdk/math/__init__.py src/swarm_sdk/compute/scoring.py
command rm -rf src/swarm_sdk/gpu src/swarm_sdk/math
```

- [ ] **Step 3: Rewrite references (math first, then gpu; order matters only for readability)**

```bash
rg -n "swarm_sdk\.math import|swarm_sdk import math|from swarm_sdk import gpu" src tests WebSearch
uv run python scratch/merge_tools/rewrite.py swarm_sdk.math=swarm_sdk.compute.scoring swarm_sdk.gpu=swarm_sdk.compute
```
Expected: the script prints the files in Files. Caveat: slash form `src/swarm_sdk/math/__init__.py` (if any doc names it) becomes `src/swarm_sdk/compute/scoring/__init__.py`, which is wrong: run `rg -n "compute/scoring/__init__" .` and fix any hit to `compute/scoring.py` by hand. Check `pyproject.toml`: `rg -n "compute" pyproject.toml` shows `src/swarm_sdk/compute/opencl_math.py` in the ruff per-file list.

- [ ] **Step 4: Gate**

Layout test PASS; `uv run python scratch/merge_tools/check_imports.py` → `0 failing module(s)`; `uv run python -c "import swarm_sdk.compute.scoring"`; full gate (Task 5, Step 1); import time: run the importtime loop (3 runs). If `swarm_sdk.compute.scoring` now drags `opencl_math` into light paths and cold import exceeds 0.55 s, stop and report (do not add lazy shims without asking).

- [ ] **Step 5: Commit (only if the user asked)**

```bash
git add -A src/swarm_sdk tests pyproject.toml README.md docs/Molten.md
git commit -m "refactor: merge math and gpu into compute"
```

---

### Task 5: Final sweep and report

**Files:**
- Modify: `AGENTS.md`/`README.md` repo-map rows if any still describe the old folders.

- [ ] **Step 1: Full gate**

```bash
uv run --extra dev --extra faiss --extra pydantic-ai --extra observability pytest -c /dev/null --rootdir=tests -o asyncio_mode=auto tests -q --tb=no -p no:cacheprovider --continue-on-collection-errors 2>&1 | tail -7
uv run ruff check src tests | tail -2
uv run --extra dev --extra observability ty check src 2>&1 | rg -c "^(error|warning)"
uv run python -m compileall -q src; echo compile=$?
uv run python scratch/merge_tools/check_imports.py
for i in 1 2 3; do uv run python -c "import time;t=time.perf_counter();import swarm_sdk.core.swarm;print(round(time.perf_counter()-t,3))"; done
```
Expected: `4 failed, 485+ passed, 1 error` with the same 5 names; ruff `All checks passed!` (pre-existing findings in untouched files, if any, are not new); ty count at most `15`; `compile=0`; `0 failing module(s)`; import times about 0.43–0.49 s.

- [ ] **Step 2: Reference sweep**

```bash
rg -n "swarm_sdk[./](server|execution|observability|prompting|math|gpu)\b" . --glob '!docs/superpowers/**' --glob '!.venv' --glob '!uv.lock' --glob '!scratch/**' --glob '!.git'
```
Expected: no output. Any hit is fixed by hand (a doc sentence or a string the script's word boundary skipped).

- [ ] **Step 3: End-to-end smoke**

```bash
uv run python -m swarm_sdk.cli --help | head -5
uv run python -c "from swarm_sdk import Settings, SwarmSDK, RunResult; print('public API ok')"
```
Expected: CLI usage text; `public API ok`.

- [ ] **Step 4: Report**

Report per the handoff format: outcome (the 4 merges and new tree), files (moves via `git mv`), verification (numbers above vs baseline), not run (merge E, `swarm_sdk.agents.validate` fails on the missing `Agents/` dir exactly as before), rollback (`$S/merge-before.tgz`; per-merge `git mv` reversal if no auto-commit intervened).
