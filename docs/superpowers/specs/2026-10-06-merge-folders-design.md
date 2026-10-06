# Merge small `swarm_sdk` folders (A–D) — design

Status: draft for review. Date: 2026-10-06. Path: architectural (import paths change).

## Goal
Fewer, more cohesive packages under `src/swarm_sdk/` with the same behavior. The user asked to
focus on merging folders (after the function-level refactor of round 1) and to leave
`vault.py` out of scope (not deleted: it is imported by `config/settings.py`, `core/swarm.py`,
`core/jev_router.py`, `serving/`, `models/chat.py`, `cli.py` and the `swarm-vault` script).

## Non-goals
- Merge E (`memory` into `retrieval`, ~23 imports): separate follow-up after A–D are green.
- No behavior or signature changes; no compatibility shims (single-user repo, every importer
  is in this repo and is updated); no change to `vault.py`, `pb/`, or the public API
  (`swarm_sdk.__init__`: `Settings`, `SwarmSDK`, `RunResult`).
- Historic specs/plans under `docs/superpowers/` keep their old paths (they are records).

## Target layout (changed packages only)
| Merge | From | To |
|---|---|---|
| A | `server/graphs.py` (`server/__init__.py` is only a re-export, dropped) | `serving/graphs.py`; not re-exported from `serving/__init__.py` (it would import langgraph whenever `swarm_sdk.serving` is imported); `rg` shows nothing imports the `swarm_sdk.server` package names |
| B | `execution/{concurrency,executor,fanout}.py`, `observability/{metrics,tracing,usage}.py` | `runtime/` with the same module names; `execution/__init__` and `observability/__init__` exports merge into `runtime/__init__.py` |
| C | `prompting/budget.py` (+ `__init__` exports) | `models/budget.py` |
| D | `gpu/{lazy_dispatcher,opencl_math,report}.py` + `gpu/__init__` API; `math/__init__.py` | `compute/{lazy_dispatcher,opencl_math,report}.py` + `compute/__init__.py` (the gpu API); `math/__init__.py` becomes `compute/scoring.py` (not re-exported, `l2_norm` exists in both) |

`runtime` is the name `decorators.py` and `orchestrator/graph.py` already (wrongly) refer to.
Evidence for the shape: inbound imports measured with an AST pass — `execution` 8,
`prompting` 3, `math` 3, `gpu` 5, `observability` 2; `execution.fanout` imports `models`
lazily (inside a function), so `runtime` -> `models` stays a lazy edge.

## Mechanics (per merge, A then B then C then D)
1. `git mv` files (history follows); create/merge the new `__init__.py`.
2. Rewrite imports with `rg -l` + exact-path replacement for: `src/`, `tests/`, `WebSearch/`,
   `langgraph.json` (`./src/swarm_sdk/server/graphs.py` -> `.../serving/graphs.py`),
   `pyproject.toml` (ruff per-file ignore `src/swarm_sdk/gpu/opencl_math.py` and any
   `memory/` paths untouched), `AGENTS.md`, `README.md`, `Toolchain.md`, `docs/Molten.md`.
   String targets in tests (`monkeypatch.setattr("swarm_sdk.execution.concurrency...")`)
   included.
3. Delete the emptied folders (including stale `__pycache__`).
4. Fix the two stale `swarm_sdk.runtime` references (they become correct).
5. Gate before the next merge (all must hold):
   - full suite no worse than today: 485 passed; failures only the 5 pre-existing
     (`test_spawn_orchestrator` x2, `test_vault_keys` x2, `tests/test_autonomous.py` error);
   - `ruff check src tests`-clean for touched files, `ty check src` not above 15;
   - `compileall -q src`; `python -c` imports every module under `swarm_sdk` (walk with
     `pkgutil.walk_packages`), optional-dependency modules tolerated by name;
   - `rg "swarm_sdk\.(server|execution|observability|prompting|math|gpu)\b"` finds nothing
     outside `docs/superpowers/`;
   - `python -X importtime -c "import swarm_sdk.core.swarm"` not slower than ~0.46 s.
6. After D: `uv run python -m swarm_sdk.cli --help` and a dry import of
   `src/swarm_sdk/serving/graphs.py` (the LangGraph factory) as an end-to-end smoke.

## Risks
- Missed dynamic import string or config path (mitigated by the walk-all-modules import and
  the final `rg` sweep; `langgraph.json` and `pyproject.toml` edited by hand).
- The editable install caches nothing by path, but `uv run` re-syncs: run the gate through
  `uv run` so the venv sees the new layout.
- Another process auto-commits this worktree (e.g. `fe4e5da`): moves may land in commits
  mid-way; each merge is made and gated within one command batch to keep commits coherent.
- Pytest cannot collect from the repo root (root `__init__.py` imports `WebSearch`); use the
  documented `-c /dev/null --rootdir=tests -o asyncio_mode=auto` invocation.

## Rollback
Scratchpad tarball of `src/` and `tests/` before step A. Per merge: `git mv` is reversible
with `git checkout -- <old paths>` plus deleting the new files, as long as no auto-commit
intervened; the tarball is the fallback.

## Open items for the reviewer
- Names: `runtime` and `compute` (alternatives: `core/runtime`, `gpu` kept with math inside).
- Merge E timing (separate spec after A–D).
