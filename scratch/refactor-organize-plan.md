# Workspace organize plan (read-only pass, 2026-10-15)

Author: Refactor agent. No project file was changed. Only this file was created
(and the `scratch/` directory, which did not exist on disk).
Labels: **verified** = a command was run; **inferred** = reasoned, not run.

## 1. Current layout map (evidence)

| Path | What it is | Evidence |
| --- | --- | --- |
| `Agents/` (23 MB) | about 55 persona dirs plus `Extra/`, `_test/`, `math/`, `tests/`, `pasta sem título/` | `ls Agents` |
| `Core/` (284 MB) | `Orchestration` (own `pixi.toml`), `Websearch`, `src/src/swarm_sdk`, `Sdk` (only `__pycache__`), `tests/test_syntax.py` | `ls Core Core/src` |
| `Farm/` (723 MB) | `BotDeal`, `TechNews`, each with `src` and `tests` | `ls Farm` |
| `Modules/Prediction` | near-copy of `RefactorOpenCL/Prediction` | `diff -rq` shows only caches in Modules; `BotDeal` and `Database` only in RefactorOpenCL |
| `Tools/WebSearch` | untracked tree, not its own repo; `git rev-parse --show-toplevel` returns Workspace | command run |
| `LangSwarm/` | separate repo, branch `chore/initial-repo-config`, holds `worktrees.yml` lane map | `git -C LangSwarm status -sb` |
| `RefactorOpenCL/` | linked worktree: `.git` file points to `/Users/usuario/Myworkspace/Swarm/.git/worktrees/RefactorOpenCL`, branch `refactor/shared-opencl-helpers` | `cat RefactorOpenCL/.git`; the gitdir exists today |
| `PyStart/` (1.9 GB) | separate repo with its own pixi, uv, `.venv` and `.pixi` | `ls PyStart`, `du` |
| `py315/` (811 MB) | stub package (`src/py315/__init__.py`) with its own pixi, `.venv`, `.pixi` | `ls py315` |
| `Learn`, `Tester` | root symlinks `Learn -> Extra/Learn`, `Tester -> Benchmarket`, both dangling (the targets live under `Agents/`) | `ls -la`; `ls -d Extra Benchmarket` fails |
| `scratch/` | missing on disk; git still tracks `scratch/LLM-1PASSWORD-ENV.md` and `scratch/enable-cursor-llm-models.py` as deleted | `git ls-files`, `git status` |
| Root configs | `pixi.toml`, `pyproject.toml`, `ruff.toml`, `ty.toml`, `biome.json`, `coordination.yaml`, `pixi.lock` | `ls -la` |
| Git state | only 3 files tracked; about 80 untracked entries; no root `.gitignore` | `git ls-files`, `git status --short \| wc -l`, `cat .gitignore` |

Quality baseline (verified, `--no-cache`): `ruff check .` reports 296 errors
(174 E501, 54 I001, 25 UP006), mostly in `Agents/Extra` (159) and
`Tools/WebSearch` (42). `ruff format --check .` would reformat 125 of 1276 files.
The pytest baseline was not run (it writes caches; this pass is read-only).

## 2. Ranked smells (value / risk)

| # | Smell | Value | Risk | Evidence |
| --- | --- | --- | --- | --- |
| S1 | No `.gitignore` at root; caches, `.DS_Store`, `.venv`, `.pixi`, `__pycache__` show up untracked | High | Very low | `cat .gitignore` fails; `git status` lists `.DS_Store` and `__pycache__` |
| S2 | Two dangling symlinks `Learn` and `Tester` | Medium | Very low | targets do not exist at root |
| S3 | Stale `pyproject.toml`: project `langgraph-swarm-sdk`, `requires-python >=3.14.5`, ruff target py314, testpaths `tests` (no root `tests/`), ty on `.venv`. It duplicates `ruff.toml` and `ty.toml`, which win for ruff. CLAUDE.md says no pyproject for new config | High | Medium (hatch build refers to `src/swarm_sdk`, which is not at root; `[project.scripts]` and extras may be used by someone) | `sed` of pyproject; `ls src` absent |
| S4 | Config drift: `ruff.toml` `src` lists `src`, `WebSearch`, `Prediction`, `Main`, none of which exist at root; `ty.toml` and the `types` task exclude `src/swarm_sdk/...` paths that do not exist at root | Medium | Low | `ruff.toml`, `pixi.toml` |
| S5 | `RefactorOpenCL` worktree depends on `~/Myworkspace`, which CLAUDE.md says is archived (`scratch/Myworkspace-2026-10-15.tar.zst`). If that dir is removed the worktree breaks | High | High (never move by hand) | `cat RefactorOpenCL/.git` |
| S6 | Duplicate code: `Modules/Prediction` vs `RefactorOpenCL/Prediction` vs `Agents/Prediction` vs `Farm/BotDeal/Prediction`; `Core/src/src/swarm_sdk` vs `RefactorOpenCL/src/swarm_sdk` (123 differing entries) | High | High (drift unknown, contracts) | `diff -rq` |
| S7 | Odd names under `Agents/`: `pasta sem título` (empty), `_test`, `math`, `Benchmarket` (typo of Benchmarker), `Extra` | Medium | Medium (`coordination.yaml`, `Codebase.md` reference `Agents/_test`, `Agents/math`) | `rg` |
| S8 | `Core/src/src` doubled directory; `Core/Sdk` holds only `__pycache__`; `Core/Orchestration/pixi.toml` plus root pixi plus `PyStart` and `py315` pixi = four environments | Medium | Medium | `ls` |
| S9 | `py315/` looks like a leftover stub (811 MB env, one empty `__init__.py`) | Medium (disk) | Medium (may be the wheel build env) | `ls py315`, `du` |
| S10 | Root `README.md` is an agent index (belongs in `Agents/`); `Codebase.md` and `SKILLS.md` at root | Low | Low | `head README.md` |
| S11 | Lint debt: 296 ruff errors, 125 unformatted files; `pixi run check` is red | Medium | Medium (style churn; keep separate commits) | ruff output above |
| S12 | Missing `scratch/` while git shows its files deleted | Low | Low | `git status` |

## 3. Steps (each independently reversible)

Preflight for every step: `cd ~/Desktop/Workspace` and record the baseline
`pixi run python -m pytest Core Agents -q` and `pixi run check` (not run in this
pass; the plan assumes the user records them first). Work on a feature branch;
commit only when asked.

1. **Add root `.gitignore`** (S1).
   - Command: write a new file containing `.DS_Store`, `__pycache__/`, `.pixi/`, `.venv/`, `.ruff_cache/`, `.pytest_cache/`, `.hypothesis/`, `*.pyc`, `.env`, `config.env`.
   - Rollback: `rm .gitignore` (new file, nothing lost).
   - Proof: `git status --short | wc -l` shrinks; `git ls-files` unchanged; tests unchanged.
2. **Recreate `scratch/` and re-point the two dangling symlinks** (S2, S12).
   - Command: `mkdir -p scratch && ln -sfn Agents/Extra/Learn Learn && ln -sfn Agents/Benchmarket Tester`.
   - Rollback: `ln -sfn Extra/Learn Learn; ln -sfn Benchmarket Tester` (restores the old targets).
   - Proof: `ls Learn/ Tester/` lists files; `rg -n 'Tester|Learn' coordination.yaml` still resolves; pytest unchanged.
3. **Fix `ruff.toml` and `ty.toml` path lists** (S4).
   - Command: replace stale `src` entries with real roots (`Core`, `Agents`, `Farm`, `Modules`, `Tools`) and drop excludes that match nothing (check each with `fd`).
   - Rollback: `git diff` is empty because the files are untracked, so first `cp ruff.toml ty.toml pixi.toml scratch/` as backup; restore by copying back.
   - Proof: `pixi run lint` and `pixi run types` give the same error counts as the baseline (296 for ruff).
4. **Retire `pyproject.toml` as config** (S3), only after the user confirms nobody builds `langgraph-swarm-sdk` from the root.
   - Command: `mv pyproject.toml scratch/pyproject.toml.bak` (move, not delete).
   - Rollback: `mv scratch/pyproject.toml.bak pyproject.toml`.
   - Proof: `pixi run check` and `pixi run python -m pytest Core Agents -q` equal the baseline; `pixi install --locked` still succeeds.
   - Note: `[tool.pytest.ini_options]` (asyncio_mode, pythonpath) moves to `pytest.ini` or `pixi.toml` in the same step, or tests may change behavior. Run the baseline first to see whether it matters.
5. **Move root `README.md` into `Agents/`** (S10): `git mv` is unavailable (untracked), so `mv README.md Agents/README.md`, then `rg -n 'README.md' CLAUDE.md SKILLS.md Codebase.md` to fix links in the same step.
   - Rollback: `mv Agents/README.md README.md`.
   - Proof: `rumdl-check Agents/README.md`; no broken link in `rg` output.
6. **Remove empty and typo dirs under `Agents/`** (S7), one by one: `Agents/pasta sem título` (empty, verify with `ls -A`), then decide on `_test`, `math`.
   - Command: `mv "Agents/pasta sem título" scratch/` (not `rm`).
   - Rollback: move it back.
   - Proof: `rg -n 'pasta sem' .` returns nothing; `pixi run python -m pytest Agents -q` equal to baseline.
   - Renaming `Benchmarket` to `Benchmarker` is a contract change (names appear in manifests); do it as its own step with a whole-repo `rg` rename and the `Tester` symlink updated.
7. **Collapse `Core/src/src` to `Core/src`** (S8): move `Core/src/src/swarm_sdk` up one level and update imports and `types` excludes in the same step.
   - Rollback: move it back.
   - Proof: `rg -n 'Core/src/src|src\.swarm_sdk|swarm_sdk' --glob '*.{py,toml,yaml}'` shows no stale path; pytest equal to baseline.
   - Only after step 4 so the pyproject paths are not a factor.
8. **Duplicate resolution (S6) is a separate project**: first produce `diff -r` reports into `scratch/` for each pair, then pick one source of truth per pair. Do not delete anything in this pass.
9. **Lint debt (S11)**: `pixi run ruff check --fix --select I,UP .` then `ruff format .` as two commits kept apart from structure moves.
   - Rollback: `git restore` is not possible on untracked files, so snapshot first: `tar --zstd -cf scratch/pre-lint.tar.zst Agents Core Farm Tools Modules`.
   - Proof: error count falls from 296; pytest equal to baseline.
10. **Worktree dependency (S5)**: do not move anything. Ask the owner whether `RefactorOpenCL` should be re-homed. The only supported command is `git worktree move` from the main repo at `~/Myworkspace/Swarm` (and `git worktree repair` after).
    - Proof: `git -C RefactorOpenCL status -sb` still shows the branch.

## 4. Success criteria

1. `git status --short` no longer lists caches or `.DS_Store` (step 1), checked by command.
2. `ls Learn/ Tester/` resolves (step 2).
3. `pixi run python -m pytest Core Agents -q` result equals the pre-change baseline after every step.
4. `pixi run check` has no new failures versus the baseline; ruff errors at or below 296, trending down after step 9.
5. No config references a path that does not exist (`fd`/`rg` sweep of `ruff.toml`, `ty.toml`, `pixi.toml`, `coordination.yaml`).
6. `RefactorOpenCL`, `LangSwarm` and `PyStart` repos unchanged: `git -C <dir> status -sb` identical before and after.
7. Every moved item is recoverable from `scratch/` or by the stated rollback.

## 5. Risks and unknowns

- Baseline tests were not run in this pass, so "stays green" is a plan, not a measurement. Run the baseline before step 1.
- Almost nothing is tracked (3 files), so git cannot undo moves: rollbacks rely on the `mv` inverses and the `scratch/` snapshot. Strongly consider a first commit of the tree on a feature branch (needs the user's request and a `.gitignore`, step 1).
- Unknown whether anything builds or installs `langgraph-swarm-sdk` from `pyproject.toml` (step 4), or whether `py315` is the wheel build env (S9, left alone).
- `coordination.yaml` and `Codebase.md` reference `Agents/_test` and `Agents/math`, so renames need the config updated in the same step.
- `.mcp.json`, `.claude/settings*.json`, `Tools/WebSearch/scraper/config.env` and `.env` files were not read; step 1 ignores `.env` and `config.env` but they may already be in history of other repos.
- `RefactorOpenCL` depends on the archived `~/Myworkspace`. Deleting that directory would break the worktree (S5).
- `scratch/` was missing, so this plan file created it; the two deleted tracked files in it are not restored.
