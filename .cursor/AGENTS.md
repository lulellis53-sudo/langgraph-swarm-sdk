# Cursor agent guidelines — Swarm

Scoped instructions for Agent work under `.cursor/`. Complements the root [`AGENTS.md`](../AGENTS.md); when they conflict, **root + specialist `Agents/*/AGENTS.md` win for product/runtime**, and this file wins for **how the Cursor agent operates**.

## Guidelines

1. **Read first** — callers, tests, and config that touch the same behavior before editing.
2. **Smallest correct diff** — no drive-by refactors, new abstractions, or dependencies unless required.
3. **Match the stack** — Python `>=3.14.5`, `uv run …`, Ruff + ty (see root quality gate). New modules: copy [@templates/python_static_template.py](templates/python_static_template.py) (PEP 810–ready).
4. **Prove it** — failing test → fix → gate (`pytest`, `ruff`, `ty`, `swarm_sdk.agents.validate`).
5. **No secrets** — never commit or paste `.env`, keys, or tokens.
6. **Docs after editing** — after substantive library/API edits, use **Context7** (preferred), then **Tavily** or **Exa**; tighten from current docs before claiming done.
7. **Delegated work** — use Cursor subagents (`.cursor/agents/` when present) or Swarm personas (`Agents/*`) with clear prompts; parallelize independent multitasks.

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

### 2. Check

- Locate callers, tests, and configs with search/read tools.
- Note open questions or risks before writing code.
- If the environment is blocked, report `blocked` with the exact command/error after one retry.

### 3. Plan (multitasks)

- Split into independent vs dependent steps.
- Run independent work in parallel (tool batches / subagents).
- Keep dependent steps sequential; name what each step must return.

### 4. Act

- Edit, run the relevant tests/gate for the change, and leave the tree reviewable.
- Update docs/commands only when behavior or install steps change.

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

1. Module docstring + `from __future__ import annotations`
2. Stdlib / third-party / local imports (eager stdlib OK; heavy third-party deferred — see PEP 810 below)
3. **`wrappers`** — `@wrappers.timed`, `@wrappers.logged`, `@wrappers.retry(n)` (always `@functools.wraps`)
4. **Role classes** (order): `TypeRole` → `HintRole` → `VectRole` → `MathRole` → `DbRole` → `LoopRole`
5. **Role functions**: `type_*`, `hint_*`, `vect_*`, `math_*`, `db_*`, `loop_*`
6. Explicit `__all__` (+ optional `main` smoke only under `if __name__ == "__main__"`)

### Roles at a glance

| Role | Class | Functions | Concern |
|------|--------|-----------|---------|
| type | `TypeRole` | `type_*` | Protocols, narrowers |
| hint | `HintRole` | `hint_*` | Annotations / metadata |
| vect | `VectRole` | `vect_*` | Vectors / embeddings math |
| math | `MathRole` | `math_*` | Scalar / reductions (no I/O) |
| db | `DbRole` | `db_*` | Store / connection façade |
| loop | `LoopRole` | `loop_*` | Async / batch iteration |

### PEP 810 — keep the template lazy-import safe

Swarm targets Python **3.14.x** today; PEP 810 `lazy import` syntax lands in **3.15**. Write modules so they become drop-in eligible:

| Do | Don't |
|----|--------|
| Module body = constants, `type` aliases, classes, functions only | Side effects at import (connect DB, spawn threads, warm caches) |
| Register plugins via explicit `register()` called by the app | Self-register into a global dict at import time |
| Heavy deps: import inside the function that needs them (3.14) or `lazy import` (3.15+) | Eager `import torch` / `numpy` / `transformers` at top level unless always required |
| Type-only names under `if TYPE_CHECKING:` | Force runtime import of typing-only modules |
| Keep `__init_subclass__` / metaclass registries free of import-time I/O | Rely on import order for correctness |
| Put smoke tests in `main()` behind `__main__` | Run asserts or network calls at import |

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
wrappers.{timed, logged, retry}
TypeRole / HintRole / VectRole / MathRole / DbRole / LoopRole
type_is_mapping, hint_tag, vect_l2, math_safe_div, db_uri, loop_chunked
__all__ + main() under __main__ only
```

Smoke check:

```bash
uv run python .cursor/templates/python_static_template.py
```

## Quick references

- Root agent map: [`../AGENTS.md`](../AGENTS.md)
- Swarm roles: [`../Agents/SKILLS.md`](../Agents/SKILLS.md)
- Extensions: [`extensions.txt`](extensions.txt)
- Example command: [`commands/sql-pro.md`](commands/sql-pro.md)
- Static template: [@templates/python_static_template.py](templates/python_static_template.py)
- PEP 810: <https://peps.python.org/pep-0810/>
