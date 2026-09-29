# Cursor agent guidelines — Swarm

Scoped instructions for Agent work under `.cursor/`. Complements the root [`AGENTS.md`](../AGENTS.md); when they conflict, **root + specialist `Agents/*/AGENTS.md` win for product/runtime**, and this file wins for **how the Cursor agent operates**.

## Guidelines

1. **Read first** — callers, tests, and config that touch the same behavior before editing.
2. **Think and analyse before writing** — restate the goal, map the real call path, then code. Do not thrash: no edit–lint–edit loops, no speculative retries, no “try another file” churn.
3. **One coherent place** — prefer **one module** (or the existing owner file) with clear, complete functions. Do **not** spawn many tiny files or 5-line stub helpers for the same concern.
4. **Smallest correct diff** — no drive-by refactors, new abstractions, or dependencies unless required.
5. **Match the stack** — Python `>=3.14.5`, `uv run …`, Ruff + ty (see root quality gate). New modules: copy [@templates/python_static_template.py](templates/python_static_template.py) (PEP 810–ready).
6. **Prove it** — failing test → fix → gate (`pytest`, `ruff`, `ty`, `swarm_sdk.agents.validate`).
7. **No secrets** — never commit or paste `.env`, keys, or tokens.
8. **Docs after editing** — after substantive library/API edits, use **Context7** (preferred), then **Tavily** or **Exa**; tighten from current docs before claiming done.
9. **Delegated work** — use Cursor subagents (`.cursor/agents/` when present) or Swarm personas (`Agents/*`) with clear prompts; parallelize independent multitasks only when they do not fragment the same feature across files.

## STOP — anti-patterns

| Stop | Do instead |
|------|------------|
| Looping the same edit / lint / retry without new evidence | Stop after one failure; analyse root cause; then one deliberate fix |
| Creating 3–10 micro-files for one feature | Extend the natural owner module; keep roles in one file when they share state |
| Writing 5-line stub functions that only forward or rename | Write real functions with the full logic, guards, and return contract |
| Spreading one concern across many half-finished modules | Finish one well-structured file; extract later only when reuse is proven |

## Folder design

```text
.cursor/
├── AGENTS.md           # This file — Cursor agent modus operandi
├── commands/           # Slash commands (e.g. sql-pro.md)
├── extensions.txt      # Recommended extensions install list
├── agents/             # Optional custom subagents (*.md)
├── skills/             # Optional project skills (*/SKILL.md)
├── templates/          # Static scaffolds — @templates/python_static_template.py
└── rules/              # Project rules (*.mdc) — always-on + globs
    ├── core.mdc
    ├── context7-after-edit.mdc
    ├── security.mdc
    ├── python.mdc
    ├── python-static-template.mdc
    ├── protobuf.mdc
    ├── config-yaml.mdc
    ├── swarm-agents.mdc
    ├── tests-benchmark.mdc
    └── git-docs.mdc
```

Repo (outside .cursor/) that agents must respect:

```text
├── AGENTS.md           # Project-wide coding / Swarm map
├── Agents/             # Swarm personas + per-role Benchmarks/
├── src/swarm_sdk/      # Library (pb/, orchestrator/, …)
├── config/             # swarm.yaml, model registry
├── tests/              # Unit / integration
└── benchmark/          # Shared harnesses (sql_pro, Tasks/, …)
```

| Path | Put here |
|------|----------|
| `.cursor/commands/` | Reusable `/` workflows |
| `.cursor/agents/` | Isolated specialist subagents |
| `.cursor/skills/` | On-demand skill packs |
| `.cursor/rules/` | Scoped `.mdc` rules (not plain `.md`) |
| `.cursor/templates/` | Static scaffolds (Python module layout, …) |
| `Agents/*/Benchmarks/` | Role-scoped notes only; runners stay in `benchmark/` |

## Modus operandi

Operate in this loop. Do **not** skip **Check**. Do **not** skip **Context7 after editing** on library/API work.

```text
Think → Check → Plan (multitasks) → Act → Context7 (after edit) → Tighten → re-Check
```

### 1. Think

- Restate the goal and success criteria in one or two sentences.
- Identify constraints (scope, files off-limits, secrets, quality gate).
- Prefer the existing pattern in-repo over inventing a new one.
- Decide the **single target file** (or minimal set) before opening the editor.

### 2. Check

- Locate callers, tests, and configs with search/read tools.
- Note open questions or risks before writing code.
- If the environment is blocked, report `blocked` with the exact command/error after one retry.
- Do not start a second implementation path while the first is unfinished.

### 3. Plan (multitasks)

- Split into independent vs dependent steps.
- Run independent work in parallel (tool batches / subagents) only when files/concerns do not overlap.
- Keep dependent steps sequential; name what each step must return.
- Prefer one solid module with role-grouped functions over a shower of micro-files.

### 4. Act

- Write complete functions (logic + edges + clear returns), not 5-line placeholders.
- Edit the chosen file(s), run the relevant tests/gate, and leave the tree reviewable.
- Update docs/commands only when behavior or install steps change.
- If a fix fails once with a clear error, analyse — do not loop blindly.

### 5. Context7 (after editing)

- After the edit lands, query **Context7 MCP** for current docs (resolve library id → query-docs).
- Fall back to **Tavily** or **Exa** when Context7 has no coverage or you need live web confirmation.
- Apply only what improves correctness, security, or maintainability — do not bloat the diff.

### 6. Think / Tighten

- Integrate doc findings; drop obsolete assumptions.
- Confirm the smallest change still satisfies the goal; re-run checks if you changed code again.
- Summarize outcomes briefly for the user (what changed, how to verify).

## Static Templates

Canonical scaffold (attach with `@`): [@templates/python_static_template.py](templates/python_static_template.py)

Also linked from root [`../AGENTS.md`](../AGENTS.md) and every `Agents/*/AGENTS.md`. Rule: [`rules/python-static-template.mdc`](rules/python-static-template.mdc).

> **Note:** There is no published **PEP 850**. For static / import-deferred module design, follow **[PEP 810 – Explicit lazy imports](https://peps.python.org/pep-0810/)** (Final; Python 3.15+). Companion tooling: Meta Lifeguard (`lifeguard-lazy-imports`). See also [PEP 649](https://peps.python.org/pep-0649/) / [PEP 749](https://peps.python.org/pep-0749/) (deferred annotation evaluation).

### When to use

- Creating a **new** module under `src/swarm_sdk/` (not drive-by edits).
- Copy the file, rename it, **delete unused role sections**, keep remaining roles contiguous.
- Do **not** import the template from runtime package code.

### Required shape

1. **Always initiate with future annotations** — first statement after the module docstring:

   ```python
   from __future__ import annotations
   ```

2. Stdlib / third-party / local imports (eager stdlib OK; heavy third-party deferred — see PEP 810 below)
3. **`wrappers`** — `retry_transient` (transient errors only), `timed` (when `SWARM_PROFILE`), `logged`
4. **Role classes**: `TypeRole` → … → `BatchRole` → `CoworkRole` (`LoopRole` = `BatchRole`); **lite** template for small modules
5. **Role functions**: `type_*`, …, `batch_*` / `loop_*`, `cowork_*`; runtime caps: `swarm_sdk.execution.concurrency`
6. Explicit export list named `__all__` (+ optional `main` smoke only under a `__main__` guard)

### Roles at a glance

| Role | Class | Functions | Concern |
|------|--------|-----------|---------|
| type | `TypeRole` | `type_*` | Protocols, narrowers |
| hint | `HintRole` | `hint_*` | Annotations / metadata |
| vect | `VectRole` | `vect_*` | Vectors / embeddings math |
| math | `MathRole` | `math_*` | Scalar / reductions (no I/O) |
| db | `DbRole` | `db_*` | Store / connection façade |
| batch | `BatchRole` | `batch_*`, `loop_*` | Bounded batch/async (`LoopRole` alias) |
| cowork | `CoworkRole` | `cowork_*` | PEP 703; use `swarm_sdk.execution.concurrency` in runtime |

### Free-threading and agent cowork (PEP 703)

- `swarm_sdk.execution.concurrency.parallel_cap()` — shared with `executor` thread pool.
- `BatchRole.gather_limited(..., limit=None)`; orchestrator siblings claim disjoint `files` per wave.

### PEP 810 — keep the template lazy-import safe

Swarm targets Python **3.14.x** today; PEP 810 `lazy import` syntax lands in **3.15**. Write modules so they become drop-in eligible:

| Do | Don't |
|----|--------|
| Module body = constants, `type` aliases, classes, functions only | Side effects at import (connect DB, spawn threads, warm caches) |
| Register plugins via explicit `register()` called by the app | Self-register into a global dict at import time |
| Heavy deps: import inside the function that needs them (3.14) or `lazy import` (3.15+) | Eager `import torch` / `numpy` / `transformers` at top level unless always required |
| Type-only names under `if TYPE_CHECKING:` | Force runtime import of typing-only modules |
| Keep `init_subclass` / metaclass registries free of import-time I/O | Rely on import order for correctness |
| Put smoke tests in `main()` behind a `__main__` guard | Run asserts or network calls at import |

Forward-compat sketch (when on 3.15+):

```python
# lazy import numpy as np          # PEP 810 — deferred until first use of np
# lazy from swarm_sdk.gpu import opencl_math
```

On 3.14 today, prefer:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

def vect_l2(a: Sequence[float], b: Sequence[float]) -> float:
    # heavy optional deps stay inside the body when not always needed
    ...
```

Optional static check (Lifeguard / lazy-import eligibility):

```bash
uv tool run lifeguard --help   # see ~/Documentos/Lifeguard.md
```

### Skeleton outline (do not paste wholesale into runtime)

```text
wrappers.{retry_transient, timed, logged}
TypeRole / … / BatchRole / CoworkRole
type_is_mapping, …, batch_chunked, cowork_parallel_cap
public __all__ list + main() only when run as __main__
```

Smoke check:

```bash
uv run python .cursor/templates/python_static_template.py
uv run python .cursor/templates/python_static_template_lite.py
```

## Quick references

- Root agent map: [`../AGENTS.md`](../AGENTS.md)
- Swarm roles: [`../Agents/README.md`](../Agents/README.md)
- Extensions: [`extensions.txt`](extensions.txt)
- Example command: [`commands/sql-pro.md`](commands/sql-pro.md)
- Static template: [@templates/python_static_template.py](templates/python_static_template.py)
- PEP 810: <https://peps.python.org/pep-0810/>
