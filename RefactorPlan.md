# Code Refactoring Plan

## Objective

Refactor the merged codebase in small, reversible steps. Reduce oversized
modules and unclear dependency boundaries while preserving public imports,
runtime behavior, provider behavior, and product-owned paths. This plan is
based on a static review of tracked Python code across the active worktrees;
it does not claim that all runtime behavior has been audited.

Branch integration comes first. Follow [`Mergeplan.md`](Mergeplan.md) to
establish the canonical tree, then apply this plan to the reviewed integration
tip. All `swarm_sdk` code is planned to live under root `Core/`, as described
in [`Codebase.md`](Codebase.md). Do not combine that directory move with
file-level refactors.

## Evidence and scope

The inventory used tracked Python files at the 12 source worktree tips and
integration `main`. Python AST parsing reported **0 parse/read errors** in each
tree. Branch trees contain shared SDK history, so the counts overlap and must
not be added together.

| Worktree branch | Tracked Python files | Approx. source lines | Functions | Classes |
| --- | ---: | ---: | ---: | ---: |
| `feat/ab-cache-perf` | 400 | 68,924 | 3,416 | 420 |
| `main` integration tip | 411 | 71,856 | 3,526 | 425 |
| `Agents` | 313 | 53,468 | 2,816 | 324 |
| `newsletter` | 96 | 16,316 | 714 | 124 |
| `NSFW` | 391 | 67,086 | 3,353 | 413 |
| `TechNews` | 26 | 2,443 | 182 | 22 |
| `refactor/shared-opencl-helpers` | 392 | 67,112 | 3,351 | 413 |
| `BotDeal` | 161 | 27,116 | 1,365 | 196 |
| `feat/proxy-routing` | 427 | 76,077 | 3,906 | 463 |
| `feat/model-gateway` | 375 | 65,873 | 3,305 | 404 |
| `Prediction` | 217 | 36,169 | 1,733 | 262 |
| `WebScraper` | 189 | 34,464 | 1,768 | 270 |
| `Websearch` | 182 | 33,514 | 1,388 | 231 |

`scc` with ignored files excluded counted 407 Python files, 70,848 total lines,
50,599 code lines, and aggregate complexity 8,204 in integration `main`.
The difference from the tracked-file AST count is due to scanner ignore and
file-selection behavior. The complexity score is a prioritization signal, not a
quality grade.

### Refactor candidates

These are review candidates based on size, structural outline, and measured
complexity. Split only where responsibilities and tests confirm a stable
boundary; line count alone is not a reason to split.

| Candidate in observed branch | Evidence | First decomposition to investigate |
| --- | --- | --- |
| `WebSearch/frontend/providers.py` (`main`) | 740 lines; `scc` complexity 211, highest in scan | Provider-specific adapters, response normalization, and fan-out orchestration. Keep provider behavior injectable and test each adapter independently. |
| `WebSearch/browser_agent.py` (`main`) | 813 lines; complexity 150 | Separate model/tool setup, search workflow, and result/context shaping only if their interfaces are already distinct. |
| `src/swarm_sdk/models/chat.py` (`main`) | 556 lines; complexity 127 | Separate provider construction/selection from chat invocation only after preserving route selection and lazy optional imports. |
| `WebSearch/frontend/fanout.py` (`main`) | 422 lines; complexity 125 | Review fan-out limits, failure aggregation, and result ordering; extract only independent policies. |
| `src/swarm_sdk/core/lifeguard_ast.py` (`main`) | 499 lines; complexity 116 | Separate AST rule definitions from traversal/reporting if the rule API can remain stable. |
| `src/swarm_sdk/retrieval/rag_ingest.py` (`main`) | 498 lines; complexity 116 | Separate ingestion orchestration from parsing/chunk preparation and persistence. |
| `Agents/benchmark/Tasks/agent_suite/suite.py` (`main`) | 825 lines | Split benchmark case definitions, execution, and result aggregation; preserve benchmark output schema. |
| `src/swarm_sdk/cli.py` (`main`) | 620 lines; complexity 109 | Separate parser/command registration from command handlers; preserve entry points and exit behavior. |
| `src/swarm_sdk/core/jev_router.py` (`Agents` and related tips) | Up to 597 lines in the inventory | Separate decision policy, model-tier selection, and trace/result serialization behind existing public contracts. |
| `MCP/websearcher_mcp.py` (`feat/proxy-routing`) | 1,008 lines; adjacent backup copy is 986 lines | Compare active implementation and dated backup; extract MCP transport, search routing, and response formatting only after identifying the canonical implementation. |
| `Agents/math/algorithms/catalog.py` (`main` branch family) | 1,029 lines | Split algorithm registry/data from implementations and metadata validation; retain deterministic registration. |
| `src/swarm_sdk/gpu/opencl_math.py` (multiple branches) | 730–741 lines; embeds OpenCL kernel source | Separate kernel source, device/context lifecycle, and array operations without changing numerical behavior or import-time device discovery. |
| `Prediction/br_hardware.py` (`BotDeal`, `Prediction`, and related tips) | 647–706 lines across tips | Separate hardware/data acquisition, feature construction, and forecast orchestration after identifying shared versus BotDeal-specific behavior. |

The AST import-frequency scan shows repeated references to
`swarm_sdk.retrieval.embeddings`, `swarm_sdk.core.swarm`,
`swarm_sdk.config.settings`, `swarm_sdk.agents.manifest`, and
`swarm_sdk.orchestrator.plan`. Treat these as dependency hubs to inspect, not
automatic extraction targets. Import frequency alone does not prove a cycle or
bad design.

The branch map found exact-content duplicates across different paths in the
branch snapshots. No exact duplicate Python files were found inside an
individual worktree during the per-worktree scan. Classify duplicate groups
before action: tests/fixtures, archives, generated data, and templates may be
intentional. Never delete a same-name file based only on its name.

## Architecture rules for the refactor

1. Keep one canonical SDK source tree at `Core/` and one canonical
   implementation of each integration. Branch histories are merged through
   Git; do not copy inherited SDK folders from each lane into parallel trees.
2. Preserve public API and import paths during file refactoring. Path moves to
   `products/` or `packages/` are a later migration with their own tests.
3. Keep dependency direction explicit: products may depend on packages; the
   SDK must not import product internals. Agents describe orchestration and
   should call declared SDK/product interfaces rather than duplicate logic.
4. Keep provider, GPU, database, filesystem, and network boundaries injectable
   so tests can use local fakes. Do not add live network requirements to unit
   tests.
5. Preserve optional-dependency behavior and lazy imports. Do not turn an
   optional feature into an import-time requirement while extracting modules.
6. Do not combine behavior changes, dependency changes, directory moves, and
   broad formatting in one refactor commit.
7. Use the existing Python static template for any new standalone Python
   module, trimmed to the roles it needs.

## Baseline and verification policy

The recorded pre-merge benchmark baseline was **50 failed, 1,577 passed, and
7 skipped**. Failure families included SQL Pro statement validation, AST and
docstring standards checks, WebSearch contract expectations, provider-key
assumptions, local transport restrictions, vault names, and forecast config.
Before implementation, rerun and save exact failing test IDs on the final
integrated tree. Every later checkpoint must show that no new failures were
introduced; baseline failures are not to be described as passing.

For each refactor slice:

- Add or identify focused behavior tests before changing production code.
- Compare before/after structure with `difft --display json` for moves or
  mechanical extraction, and review the normal Git diff for behavior changes.
- Run the narrow tests first, then the relevant package tests and static checks.
- Run the repository-wide quality gate at phase checkpoints, not after every
  file move.
- Record timings only when the change claims a performance improvement; use
  repeatable workloads and `hyperfine`, with model/network calls excluded.

The source review pass used `ast-grep outline` on representative high-risk
modules and `scc --by-file` for size/complexity ranking. Use the same tools on
the final merged tree when selecting exact symbol boundaries.

## Implementation task list

### Phase 0: Stabilize the integration base

#### Task 0.1: Finish branch integration

**Scope:** Follow `Mergeplan.md` in the isolated integration worktree.

**Acceptance criteria:**

- [ ] All intended committed lane tips are integrated, with TechNews imported
  only under its owned subtree.
- [ ] Dirty source worktrees remain unchanged.
- [ ] MCP/WebScraper/WebSearch and BotDeal/Prediction overlaps have a written
  canonical-path decision and no duplicate implementation trees.

**Verification:** Git history, `git worktree list`, `git status` snapshots,
submodule state, duplicate-content inventory, and merge-path review.

**Dependencies:** None. This task blocks every code refactor task.

### Phase 1: Establish architecture and behavior guardrails

#### Task 1.1: Record import and ownership boundaries

**Scope:** `src/swarm_sdk/`, `Agents/`, `WebSearch/`, `MCP/`, `Prediction/`,
`Newsletter/`, `TechNews/`, `tests/`, `pyproject.toml`, runtime/config manifests.

**Acceptance criteria:**

- [ ] Each source subtree has a named owner and allowed dependency direction.
- [ ] Runtime imports from product code and product imports from other product
  internals are listed for review.
- [ ] Public entry points, console scripts, LangGraph factory paths, protobuf
  generation, and documented import paths have an explicit compatibility list.

**Verification:** AST-based import inventory plus search for dynamic import
strings, entry points, and config-controlled module paths.

**Dependencies:** Task 0.1.

#### Task 1.2: Capture the final baseline

**Scope:** Full documented quality gate and known failing tests on integrated
`main`.

**Acceptance criteria:**

- [ ] Exact test IDs, error output, static-check output, and environment extras
  are recorded outside ephemeral console output.
- [ ] The quality gate can be run with the repository’s single shared `.venv`.
- [ ] Any changed baseline is explained before a file is refactored.

**Verification:** Run the documented benchmark tests, Ruff, `ty`, and agent
manifest validator; compare to the recorded pre-merge baseline.

**Dependencies:** Task 0.1.

### Phase 2: Refactor focused, high-risk modules

#### Task 2.1: Split WebSearch provider responsibilities

**Files:** `WebSearch/frontend/providers.py`, its direct tests, and only the
smallest required import/export files.

**Acceptance criteria:**

- [ ] Each provider adapter has a focused test for success, malformed output,
  timeout/error handling, and missing credentials where applicable.
- [ ] Provider result normalization and fan-out policy have explicit inputs
  and outputs.
- [ ] Existing `SearcherSpec`, `SearchFn`, and public provider imports remain
  compatible.

**Verification:** Focused provider tests, WebSearch suite, Ruff, `ty`, import
smoke, and AST structural diff review.

**Dependencies:** Tasks 1.1 and 1.2.

#### Task 2.2: Extract WebSearch browser-agent layers

**Files:** `WebSearch/browser_agent.py` and its direct tests.

**Acceptance criteria:**

- [ ] Model construction, tool wiring, orchestration, and response shaping have
  clear module boundaries based on actual call paths.
- [ ] Tests do not require live provider keys or network access.
- [ ] Public agent factory and CLI/tool behavior remain unchanged.

**Verification:** Focused browser-agent/tool tests, WebSearch suite, lazy-import
check, and import smoke.

**Dependencies:** Task 2.1.

#### Task 2.3: Reduce CLI command coupling

**Files:** `src/swarm_sdk/cli.py`, CLI tests, `pyproject.toml` entry points only
if required.

**Acceptance criteria:**

- [ ] Parser registration and command handlers are separated by coherent
  command responsibility.
- [ ] `low-swarm` arguments, exit codes, output, and error behavior remain
  compatible.
- [ ] Importing CLI help does not load optional providers or initialize
  external services.

**Verification:** CLI parser/command tests, `uv run low-swarm --help`, static
checks, and cold-import comparison if startup behavior changes.

**Dependencies:** Tasks 1.1 and 1.2.

### Checkpoint A: After Tasks 2.1–2.3

- [ ] No new baseline test failures.
- [ ] No new import cycles or eager optional dependencies.
- [ ] Public command/provider contracts remain unchanged.
- [ ] Review the diff before beginning SDK internals.

### Phase 3: Refactor SDK responsibilities

#### Task 3.1: Separate chat provider construction from invocation

**Files:** `src/swarm_sdk/models/chat.py`, model selection code, focused model
tests.

**Acceptance criteria:**

- [ ] Route/model resolution and invocation have narrow interfaces.
- [ ] Provider adapters remain selected by the existing route registry.
- [ ] Optional providers stay lazy and missing credentials produce the same
  documented errors.

**Verification:** Model selection tests, provider-factory tests with fakes,
agent graph tests, `ty`, and cold import.

**Dependencies:** Checkpoint A.

#### Task 3.2: Separate retrieval ingestion, cache policy, and storage

Database schema, durability, and ownership work is broken down in the focused
[`tasks/plan.md`](tasks/plan.md) plan and tracked in [`tasks/todo.md`](tasks/todo.md).
That plan keeps vector memory, response cache, LangGraph checkpoints, and
product-owned Parquet storage separate; its tasks target the current integrated
source paths until this plan's later Core/product move.

**Files:** `src/swarm_sdk/retrieval/{rag_ingest,cache,embeddings}.py` and
focused retrieval/memory tests.

**Acceptance criteria:**

- [ ] Embedding, chunk preparation, cache policy, persistence, and orchestration
  have clear ownership with no duplicated vector math.
- [ ] Cache keys, serialization, ordering, and backend behavior stay unchanged.
- [ ] Existing protocols remain injectable and optional backends stay optional.

**Verification:** Retrieval/cache/memory focused tests, backend contract tests,
Ruff, `ty`, and import-all check.

**Dependencies:** Task 3.1.

#### Task 3.3: Refactor `SwarmSDK` orchestration only if cohesion review supports it

**Files:** `src/swarm_sdk/core/swarm.py` and its callers/tests on the merged
tip. Re-evaluate current size after lane integration before starting.

**Acceptance criteria:**

- [ ] Construction, graph compilation, run lifecycle, memory operations, and
  provider routing have explicit seams without turning the class into a bag of
  service objects.
- [ ] `SwarmSDK`, `RunResult`, and documented imports remain stable.
- [ ] Thread/checkpointer behavior and run result accounting remain unchanged.

**Verification:** Core lifecycle, serving, and orchestration tests; import
smoke; `ty`; cold-import timing comparison.

**Dependencies:** Task 3.1 and Task 3.2.

#### Task 3.4: Isolate OpenCL kernel/device lifecycle from math API

**Files:** `src/swarm_sdk/gpu/opencl_math.py`, GPU tests, Ruff path-specific
configuration if the source path moves.

**Acceptance criteria:**

- [ ] Kernel source, device/context and buffer lifecycle, and vector operations
  can be reasoned about independently.
- [ ] Importing `swarm_sdk.gpu` does not enumerate or initialize devices.
- [ ] CPU fallback and numerical outputs remain identical within existing
  tolerances.

**Verification:** CPU-only tests, OpenCL tests when hardware is available,
kernel compilation checks, and numeric parity tests.

**Dependencies:** Tasks 1.1 and 1.2. Keep this isolated from other SDK refactors.

### Checkpoint B: After Tasks 3.1–3.4

- [ ] Run the full documented SDK/benchmark gate and compare failures to the
  integrated baseline.
- [ ] Run package import traversal in a fresh interpreter.
- [ ] Confirm `swarm_sdk.__init__`, protobuf, LangGraph factories, and CLI
  entry points still load.
- [ ] Review public API and dependency changes before proceeding.

### Phase 4: Refactor integrations and benchmark tooling

#### Task 4.1: Settle MCP, WebScraper, and WebSearch ownership

**Files:** `MCP/`, `WebScraper/`, `WebSearch/`, their tests/configs, and
references in scripts and manifests.

**Acceptance criteria:**

- [ ] Search/fetch/crawl/extraction/MCP transport each have one declared owner.
- [ ] Backup files are not imported or packaged as runtime implementation.
- [ ] No duplicate source implementation remains; tests and imports reference
  only the canonical implementation.

**Verification:** Import graph, tracked path/hash report, module tests, package
build/import smoke, and stale path search.

**Dependencies:** Task 0.1 and Tasks 2.1–2.2.

#### Task 4.2: Split benchmark suite into runner, case registry, and reporting

**Files:** `Agents/benchmark/Tasks/agent_suite/suite.py`, benchmark helpers,
and suite tests.

**Acceptance criteria:**

- [ ] Case discovery, execution, scoring, and output format have testable
  boundaries.
- [ ] Existing benchmark IDs and serialized result schema remain stable.
- [ ] The suite does not import product/runtime code it does not exercise.

**Verification:** Unit tests with deterministic fixtures, smoke run of a small
suite, and benchmark output-schema comparison.

**Dependencies:** Task 1.1; do not run concurrently with broader benchmark
contract changes.

#### Task 4.3: Modularize the agent math catalog

**Files:** `Agents/math/algorithms/catalog.py`, algorithm implementations,
catalog tests, and agent manifest references.

**Acceptance criteria:**

- [ ] Registration metadata is separated from implementation code where
  ownership is clear.
- [ ] Algorithm names, ordering, dispatch, and serialization stay stable.
- [ ] No duplicate algorithm implementation is introduced.

**Verification:** Catalog tests, deterministic ordering tests, agent validator,
and benchmark smoke.

**Dependencies:** Task 1.1.

### Phase 5: Dependency and directory migration

#### Task 5.1: Split dependency declarations by runtime boundary

**Files:** Root `pyproject.toml`, `uv.lock`, and future workspace project
metadata only after ownership boundaries are stable.

**Acceptance criteria:**

- [ ] Core SDK installs without optional forecast, scraping, GPU, and product
  dependencies unless they are truly imported by core runtime.
- [ ] Each product/package declares only dependencies it uses.
- [ ] One lock strategy and one documented environment policy remain clear.

**Verification:** Clean resolution with `uv lock --check`, minimal/core install,
each optional extra, import tests, and CI workflow review.

**Dependencies:** Tasks 0.1, 1.1, and Phase 4 ownership decisions.

#### Task 5.2: Move source directories to the `Codebase.md` target layout

**Files:** `src/swarm_sdk/` → `Core/src/swarm_sdk/`, `Agents/`, `Main/`, product and integration roots, configs,
CI, docs, workspace files, manifests, and dynamic path references.

**Acceptance criteria:**

- [ ] All `swarm_sdk` modules are under `Core/src/swarm_sdk/`, with no parallel
  SDK source tree left under root `src/` or `packages/`.
- [ ] Each directory move preserves Git history and has one canonical target.
- [ ] Imports, entry points, package discovery, protobuf generation, LangGraph
  manifests, CI path filters, and docs use the new paths.
- [ ] No compatibility shim is added without an owner, removal date, and test.

**Verification:** Focused tests after each move, import-all, package builds,
old-path search, duplicate inventory, and full quality gate.

**Dependencies:** Task 5.1 and all previous checkpoints.

## Checkpoint C: Completion

- [ ] No newly introduced test, lint, or type failures.
- [ ] All pre-existing failures have an owner and are separately tracked.
- [ ] Public imports, CLI commands, server graph factories, and protobuf tools
  work from the documented workspace root.
- [ ] Duplicate-path/hash report has no unexplained runtime-source duplicates.
- [ ] `Codebase.md`, `Mergeplan.md`, `README.md`, `AGENTS.md`, and CI reflect
  the actual final layout.

## Risks and mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Refactoring before branch integration completes | High: conflicting copies or lost lane behavior | Keep all file refactors blocked on Mergeplan Task 0.1. |
| Splitting by line count without cohesion evidence | Medium: more indirection, harder imports | Inspect AST symbols, callers, tests, and change history before choosing module boundaries. |
| Moving paths and changing behavior together | High: failures are hard to attribute | Separate path-only and behavior-only commits; preserve import compatibility. |
| New eager imports of optional providers/GPU libraries | High: breaks minimal installs and cold start | Import traversal, minimal-extra CI, and cold-import checks at each SDK checkpoint. |
| Existing baseline failures mask regressions | High: test signal is ambiguous | Save exact failing test IDs on the merged base and compare at every checkpoint. |
| Archive/backup/fixture content mistaken for duplicate runtime code | Medium: useful history or test data lost | Classify duplicate groups before deletion and document intentional copies. |
| `pyproject.toml` split destabilizes the shared environment | High: worktrees resolve different dependency graphs | Delay dependency/workspace split until source ownership is stable; preserve one shared `.venv` policy. |

## Out of scope

- Implementing these refactors in this planning pass.
- Pushing, deleting branches, or changing source worktree edits.
- Rewriting product behavior, APIs, or provider contracts for style alone.
- Removing archived docs, backups, generated artifacts, or fixtures without
  ownership evidence.
