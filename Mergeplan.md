# Branch Integration Plan

## Goal

Integrate the active worktree branches into local `main`, preserve each lane’s
unique work, and finish with one canonical copy of every product, package, and
integration folder. Keep the existing top-level layout during branch
integration; any later directory reorganization follows [`Codebase.md`](Codebase.md)
as a separate migration.

## Safety rules

- Work only in the isolated `/private/tmp/swarm-main-integration` worktree on
  `main`.
- Preserve dirty edits in every source worktree. Merge committed branch tips
  only; do not stash, reset, clean, or otherwise rewrite source worktrees.
- Before each lane, record its branch name, tip commit, status, and changed
  paths. Recheck them after integration.
- Do not push, delete branches, or change submodule contents as part of this
  plan.
- Treat branch files as project data. Keep secrets and local `.env` files out
  of merge commits.
- Use merge commits for related histories. For unrelated history, import only
  the owned subtree and explain the history treatment in the commit.

## Current integration state

The isolated `main` worktree already contains these local merge commits:

1. `54e880d` — `feat/ab-cache-perf`
2. `5197c27` — `feat/model-gateway` (to be reverted; feature excluded)
3. `f9fbefd` — `refactor/shared-opencl-helpers`

The `Agents` merge is currently in progress. Git reports all conflicts fixed,
with **214 paths staged** and the merge still requiring review and a merge
commit. The staged set contains agent changes plus changes to SDK source,
benchmark code, `pyproject.toml`, `uv.lock`, and tests. Review those changes as
part of the branch; do not discard non-`Agents/` paths just because they are
outside the persona tree.

The `Codebase.md` map and this plan are currently untracked in the source
worktree. Add them to a later, deliberate documentation commit or include them
in a merge only if their ownership and timing are clear. Do not mix them into a
lane merge by accident.

## Active branches and treatment

| Branch | Worktree lane | Planned treatment |
| --- | --- | --- |
| `feat/ab-cache-perf` | `Swarm` | Already merged; includes `NSFW` ancestry. |
| `feat/model-gateway` | `Tools/ModelGateway` | Do not retain. Revert merge commit `5197c27` after completing the current `Agents` merge; verify only gateway-specific behavior is removed. |
| `refactor/shared-opencl-helpers` | `RefactorOpenCL` | Already merged; keep its changes within SDK ownership. |
| `Agents` | `Agents` | Finish current merge after reviewing its full staged diff and validating manifests. |
| `Prediction` | `Tools/Prediction` | Merge its committed tip; retain forecast-specific code once and keep BotDeal ownership distinct. |
| `BotDeal` | `Tools/BotDeal` | Merge its committed tip; reconcile root `Database/` and `Prediction/BotDeal/` content with existing copies. |
| `newsletter` | `Modules/Newsletter` | Merge its committed tip; preserve only newsletter-owned changes from its full-repository ancestry. |
| `Websearch` | `Tools/WebSearch` | Merge its committed tip; reconcile `WebSearch/` tests/configs and inherited SDK changes. |
| `WebScraper` | `Tools/WebScraper` | Merge its committed tip after comparing with MCP/WebSearch; keep unique scraper functionality only once. |
| `feat/proxy-routing` | `Tools/MCP` | Do not merge the proxy-routing feature. Review any unrelated MCP files separately; import none without a demonstrated need and ownership. |
| `TechNews` | `Modules/TechNews` | Import only the `TechNews/` subtree because its history is unrelated to SDK `main`. |
| `NSFW` | `Modules/NSFW` | No separate merge: its committed tip is already an ancestor of `feat/ab-cache-perf`; preserve dirty source changes for a separate review. |

Branch refs and worktree paths can move. Confirm the current values with Git
immediately before each step; this table records the observed inventory, not a
license to overwrite later changes.

## Merge sequence

### 1. Complete `Agents`

- Review the staged diff by area: agent manifests/contracts, coordination,
  benchmark suite, SDK/runtime, tests, dependency metadata, and lockfile.
- Verify any removed agent is intentionally removed or replaced and that
  coordination references resolve to registered manifests.
- Keep the combined SDK exports and other deliberate conflict resolutions.
- Check whitespace and secret hygiene; then create the merge commit.
- Run focused agent validation and affected benchmark/SDK tests before moving
  to the next lane.

### 2. Remove the Model Gateway merge

- Revert `5197c27` on the isolated integration `main` after the `Agents` merge
  is committed. Use a normal revert commit with first-parent mainline so the
  shared branch history remains intact.
- Confirm the revert removes `src/swarm_sdk/serving/gateway.py`,
  `src/swarm_sdk/serving/gateway_convert.py`, their two gateway tests, and the
  gateway-specific edits to `src/swarm_sdk/serving/http.py` and
  `src/swarm_sdk/models/chat.py`.
- Review the revert diff and run focused serving/model tests. Preserve unrelated
  pre-existing provider and serving behavior.

### 3. Merge `Prediction` and `BotDeal`

- Merge `Prediction` first, then `BotDeal`, so the forecast lane is present
  before reconciling BotDeal forecast integrations.
- Compare `Prediction/BotDeal/` and root `Database/<month>/` trees across both
  branch tips using path and content inventories.
- Keep product code, source data, generated results, and fixtures distinct.
  Do not duplicate identical trees; do not delete differing data without
  verifying its owner and use.
- Run the prediction and BotDeal focused checks after their respective merges.

### 4. Merge `newsletter`

- Import the committed newsletter lane changes while preserving SDK and shared
  configuration changes only when they are unique or required by the lane.
- Keep newsletter-specific code, data, docs, and tests under the current
  `Newsletter/` path for this integration phase.
- Run newsletter-focused tests and verify shared SDK history is not copied as
  a second source tree.

### 5. Merge `Websearch` and `WebScraper`

- Merge `Websearch` first to establish the current search pipeline and its
  tests/configuration.
- Compare `WebScraper/`, any MCP content, and `WebSearch/` by path, content
  hash, import graph, and runtime responsibility.
- Merge `WebScraper` only after resolving overlap. Keep search pipeline behavior
  in `WebSearch/`; transfer genuinely unique scraper components to their
  owning integration instead of retaining a duplicate `WebScraper/` tree.
- Do not import proxy-routing commits or gateway code. MCP components are
  considered only when they are independent of those excluded features.
- Update imports, configuration, CI, and tests as one cohesive resolution.
- Verify there are no duplicate source trees, repeated entry points, or stale
  path references after these merges.

### 6. Import the `TechNews/` subtree

- Confirm `git subtree` is available and inspect its help before use.
- Split the source branch at `TechNews/` and integrate only that subtree into
  local `main`, preserving SDK history already in `main` without importing an
  unrelated second repository root.
- Verify `TechNews/src/technews/{prediction,scrape}/` and its tests arrive once.

### 7. Final tree and history review

- Run `git diff --check`, inspect `git status`, review all merge commits, and
  confirm `.gitmodules` matches tracked submodule gitlinks.
- Compare the result with the tracked-tree AST/path inventory. Search for
  exact duplicate files and same-path variants; retain intentional fixtures,
  generated files, archives, or vendored content only with a clear reason.
- Verify every active source worktree’s dirty status remains unchanged.
- Run focused checks for each lane, then the documented full quality gate.
- Record known baseline failures separately from regressions. Do not describe
  the suite as passing if existing failures remain.
- Leave local `main` available for review. Do not push or delete refs.

## Baseline and known limitations

The pre-merge full benchmark suite on local `main` reported **50 failed,
1,577 passed, and 7 skipped**. Failures included SQL Pro statement validation,
AST/docstring standards checks, stale WebSearch contracts, provider-key
assumptions, local transport restrictions, vault names, and forecast config
mismatches. The final verification must compare failures with this baseline and
report new failures separately.

AST syntax parsing across the 12 active worktrees found no parse/read errors.
This confirms Python syntax only; it does not establish runtime correctness.

## Completion checklist

- [ ] Finish and review the in-progress `Agents` merge.
- [ ] Merge `Prediction`, `BotDeal`, and `newsletter` with owned paths intact.
- [ ] Merge WebSearch/WebScraper/MCP changes with one canonical copy of overlap.
- [ ] Revert the Model Gateway merge commit and exclude proxy-routing changes.
- [ ] Integrate only the `TechNews/` subtree.
- [ ] Confirm `NSFW` committed history is included through `feat/ab-cache-perf`;
      keep its dirty work unmerged.
- [ ] Audit duplicates, submodules, secret files, and old path references.
- [ ] Confirm source worktree statuses are unchanged.
- [ ] Run and report the final quality checks against the baseline.
- [ ] Keep all results local; no push or branch deletion.
