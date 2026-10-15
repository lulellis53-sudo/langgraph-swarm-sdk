# Workspace refactor plan v2 (2026-10-15)

Supersedes `scratch/refactor-organize-plan.md`. Applies the Judge's eight fixes
(`scratch/judge-refactor-plan.json`, 80/100, approve with fixes) and adds the
`swarm_sdk` merge and the `RefactorOpenCL` findings. Nothing here has been
applied. Labels: **verified** = a command was run; **inferred** = not run.

## 1. Facts this plan rests on

- Only 3 files are tracked and there is no root `.gitignore` (verified), so git
  cannot undo moves. Rollbacks use `mv` inverses and a filtered snapshot.
- `Learn` and `Tester` are dangling symlinks (verified by the Judge).
- `RefactorOpenCL` is a linked worktree owned by `~/Myworkspace/Swarm`. It now
  lives at `~/Desktop/Workspace/RefactorOpenCL` (moved with `git worktree move`).
- `scratch/Myworkspace-2026-10-15.tar.zst` does **not** exist (verified by the
  Judge), so `~/Myworkspace` is not safely archived. Nobody removes it until the
  archive location is confirmed.
- `Core/Sdk` is empty (only `__pycache__`). `Core/src/src/swarm_sdk` holds 7
  `models/` files. `~/Myworkspace/Swarm/src/swarm_sdk` has 134 files. Three
  files differ and the `Core` copies are newer: `models/chat.py`,
  `models/registry.py`, `models/selection.py` (verified).
- pytest config lives in `pyproject.toml`: `testpaths = [Agents/benchmark,
  tests]` plus a `pythonpath` and `asyncio_mode` (corrects the v1 claim).
- `RefactorOpenCL` baseline (verified, `pytest tests`, two files ignored because
  `pandas` is missing): 739 passed, 18 failed, 5 skipped. `ruff check`: 17
  findings (11 in `tests/test_sdk_benchmark_suite.py`, 2 in `config/settings.py`).
- Workspace baseline from the Judge: ruff 296 errors (174 E501, 54 I001, 25
  UP006); `ruff format --check` would reformat 125 files. pytest and
  `pixi run check` have **not** been run.

## 2. Steps

Every step needs Step 0 recorded first. Work on a feature branch. Commit only
when asked.

0. **Baseline gate (blocking, F2).** Record, into `scratch/baseline.txt`:
   `pixi run python -m pytest Core Agents -q --tb=short`,
   `pixi run python -m pytest --collect-only -q | tail -3`, `pixi run check`,
   ruff counts, and `git -C <dir> status -sb` for `RefactorOpenCL`,
   `LangSwarm`, `PyStart`.
   Proof: the file exists and holds real counts. No later step starts without it.
0a. **Discover pass (read-only, before any edit).** Build the reference map once
   and reuse it: `rg -n 'Core/src|Core/Sdk|swarm_sdk' -g '*.{py,toml,yaml,yml,md,json}'
   > scratch/refs-swarm-sdk.txt`, `rg -n 'Agents/(_test|math|Benchmarket|Extra)'
   > scratch/refs-agents-dirs.txt`, `fd -t l . -x ls -l {}` for symlinks, and
   `pixi task list`. Proof: the three files exist and each later path edit
   cites them.
0b. **Classify every step (L1-L4) and fix the order.** L1 = Steps 1, 3, 12;
   L2 = 5, 6, 9, 10; L3 = 4, 7, 8 (public import paths, build config, tests);
   L4 = 2, 11 (history, archive). L3 and L4 steps show command, target,
   loss and rollback to the user before running.
1. **Root `.gitignore`.** New file: `.DS_Store`, `__pycache__/`, `.pixi/`,
   `.venv/`, `.ruff_cache/`, `.pytest_cache/`, `.hypothesis/`, `*.pyc`, `.env`,
   `config.env`.
   Rollback: `rm .gitignore`. Proof: `git status --short | wc -l` shrinks.
2. **Safety commit (F8, needs the user's request).** Commit the tree on the
   feature branch with explicit paths (no `git add` of everything, `.env` and
   `config.env` are ignored). This is the real undo for every later step.
3. **Fix dangling symlinks.** `ln -sfn Agents/Extra/Learn Learn` and
   `ln -sfn Agents/Benchmarket Tester`. Rollback: restore the old targets.
   Proof: `ls Learn/ Tester/` lists files.
4. **Merge `swarm_sdk` (new, blocked until the user approves the copy).**
   - Target: one canonical package, `Core/Sdk/swarm_sdk`. Full copy from
     `~/Myworkspace/Swarm/src/swarm_sdk/`, excluding `__pycache__` and `*.pyc`.
   - The 7 existing `Core/src/src/swarm_sdk/models` files are reconciled by
     `difft` for the three conflicts, keeping the newer `Core` change where it
     is a superset. The decision is the user's.
   - Rollback: delete `Core/Sdk/swarm_sdk` (nothing existing is overwritten).
   - Proof: `diff -rq -x __pycache__` against the source shows only the three
     named files; `python -c "import swarm_sdk"` with the test `sys.path`.
5. **Retire the old `Core/src/src` doubling.** After step 4, move the leftover
   `Core/src/src/swarm_sdk` up or remove it, in one pass that also edits every
   path reference once (F5): `ruff.toml`, `ty.toml`, `pixi.toml` types task,
   `Agents/ApiVaulter/agent.yaml`, `Agents/_test/model_delegation/suite.yaml`,
   `coordination.yaml`, `Modules/Prediction/__init__.py`, `Core/Websearch/*`.
   Command: `rg -n 'Core/src/src|src/swarm_sdk' --glob '*.{py,toml,yaml}'`
   lists every hit before editing.
   Proof: the same `rg` returns nothing stale; import check passes; pytest
   count equals Step 0.
6. **Config drift in `ruff.toml` and `ty.toml` (F4).** Remove paths that match
   nothing (`src`, `WebSearch`, `Prediction`, `Main`, `Agents/benchmark`
   verified missing with `fd`). Changing `src` can change first-party
   classification, so the **expected** I001 count may change. Write the
   expected count down first; do not claim "same counts".
   Backup: copy the three files to `scratch/config-backup/`.
7. **Retire `pyproject.toml` as config (F3), only after the user confirms
   nothing builds `langgraph-swarm-sdk` from the root.** Move
   `[tool.pytest.ini_options]` verbatim (`asyncio_mode = auto`,
   `pythonpath = [".", "Agents"]`) into `pytest.ini`, then
   `mv pyproject.toml scratch/pyproject.toml.bak`.
   Proof: `pytest --collect-only -q` count equals Step 0; `pixi install
   --locked` succeeds.
8. **`RefactorOpenCL` cleanup (own branch, own commit).**
   - Install `pandas` or mark the two modules with `pytest.importorskip`
     (a named reason), so 2 collection errors disappear.
   - Triage the 18 failures one by one with a root cause each
     (`test_spawn_orchestrator.py` and `test_web_evidence.py` first). Fix the
     cause; never skip or xfail without a named reason.
   - Fix the 17 ruff findings (5 auto-fixable; review the unused variables).
   Proof: `pytest tests` fully green or each remaining failure listed.
9. **Lint debt, per directory (F6).** One directory at a time, then pytest:
   `ruff check --select UP --fix <dir>`, then `--select I --fix <dir>`, then
   `ruff format <dir>`. Do not auto-fix the 9 unsafe items. pytest only covers
   `Core/tests` and `Agents/tests`, so also run `python -m compileall -q <dir>`.
   Snapshot (F1, filtered, listing checked for secrets before leaving it):
   `tar --zstd -cf scratch/pre-lint.tar.zst --exclude=config.env
   --exclude=.env --exclude=.pixi --exclude=.venv --exclude=__pycache__
   --exclude=.ruff_cache Agents Core Tools Modules` (leave out `Farm`, 706 MB).
   Check with `tar -tf ... | rg -c 'env$'` returning 0.
10. **Duplicates (S6): reports only.** `diff -rq` outputs into `scratch/` for
    `Modules/Prediction` vs `RefactorOpenCL/Prediction` vs
    `Agents/Prediction`, and `Core/Sdk` vs `RefactorOpenCL/src/swarm_sdk`
    (143 differing entries, counting method: `diff -rq | wc -l`). No deletion.
11. **`~/Myworkspace` dependency.** Do not move or delete. Confirm where the
    archive actually lives, because the one named in `CLAUDE.md` does not
    exist. Only `git worktree move` or `git worktree repair` from
    `~/Myworkspace/Swarm` may touch the worktree.
12. **Optional, low value:** move root `README.md` to `Agents/` and fix links.
13. **Odd `Agents/` dirs, one at a time.** For `pasta sem título` (verify empty
    with `ls -A`), `_test`, `math`: `rg` the name first (`scratch/refs-agents-dirs.txt`),
    `mv` to `scratch/` (never `rm`), then pytest equals Step 0. `Benchmarket`
    to `Benchmarker` is a contract rename: separate step, whole-repo `rg`
    rewrite, `Tester` symlink updated, manifests re-checked
    (`Agents/tests/test_manifests.py`).
14. **Environment consolidation (report first).** List the four environments
    (root pixi, `Core/Orchestration`, `PyStart`, `py315`) with size and last
    use (`dust -d 1`, `stat`). Decide keep/merge per env with the user; do not
    remove `py315` (811 MB) before confirming it is not the wheel build env.
15. **Docs sync.** Update `CLAUDE.md` Layout, `Codebase.md` and `SKILLS.md`
    for every moved path (`rg` each old path), then `rumdl-check` on each file.
16. **CI and hooks.** Confirm `pixi run check` is what CI runs (`.github/`);
    add `.gitignore`d paths to ruff `extend-exclude` so lint and git agree.
17. **Final gate.** Re-run Step 0 commands and diff against `scratch/baseline.txt`:
    pytest, collect-only, `pixi run check`, ruff counts, sibling-repo
    `git status -sb`. Any regression is reverted via its step's rollback.
18. **Re-judge and report.** Send the diff and `scratch/baseline.txt` to the
    Judge agent for a rescore (target 85 or higher). Report per step: command
    run, result, rollback, and what was not run.

Gates: Step 0 blocks 1-18; Step 2 blocks 4-9; Steps 4, 7, 11, 14 need explicit
user approval. Backward path: a failing proof returns control to the step's
rollback and then to 0a (unmapped caller), never forward.

## 3. Success criteria

1. `scratch/baseline.txt` exists with measured pytest, collect-only and ruff
   numbers before any change (Step 0).
2. After every step, pytest and collect-only counts equal the baseline, except
   where a step states the expected change.
3. `git status --short` no longer lists caches or `.DS_Store`.
4. `Core/Sdk/swarm_sdk` imports cleanly and differs from the source only in
   the three reviewed model files.
5. No config references a missing path (`fd`/`rg` sweep of `ruff.toml`,
   `ty.toml`, `pixi.toml`, `coordination.yaml`).
6. `RefactorOpenCL` tests: 0 collection errors and each failure fixed or
   explained; `LangSwarm` and `PyStart` `git status` identical to Step 0.
7. No secret appears in any snapshot or report.

## 4. Risks and unknowns

- pytest at the Workspace root has not been run (unmeasured, inferred green).
- Whether anything builds from `pyproject.toml` and whether `py315/` is the
  wheel build environment are unknown.
- The three conflicting model files: which side is correct is not judged.
- `.env`, `config.env`, `.mcp.json` were not read.
- The `RefactorOpenCL` worktree still depends on `~/Myworkspace/Swarm`.
