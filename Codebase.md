# Codebase Organization Plan

This is a **future-state plan**, not a description of directories that already
exist. The current checkout has `Agents/`, `CLI/`, `Main/`, `Newsletter/`,
`Prediction/`, `TechNews/`, `WebSearch/`, `src/`, `tests/`, and supporting
project directories at the root. It does not currently have top-level
`Modules/`, `Products/`, or `Models/` directories.

The goal is a clear home for the SDK, product applications, shared integrations,
agents, and project operations, while retaining one canonical copy of each
module and preserving Python import paths during migration.

## Proposed future layout

```text
Swarm/
├── products/                         # Independently useful product domains
│   ├── botdeal/
│   │   ├── src/botdeal/               # Product logic and entry points
│   │   ├── config/                    # BotDeal-owned settings/schema
│   │   ├── tests/                     # Product tests
│   │   └── README.md
│   ├── newsletter/
│   │   ├── src/newsletter/
│   │   ├── config/
│   │   ├── tests/
│   │   └── README.md
│   ├── nsfw/                          # Keep only if confirmed as a product
│   │   ├── src/nsfw/
│   │   ├── config/
│   │   ├── tests/
│   │   └── README.md
│   ├── prediction/
│   │   ├── src/prediction/             # Product-specific forecasting flows
│   │   ├── config/
│   │   ├── tests/
│   │   └── README.md
│   └── technews/
│       ├── src/technews/
│       ├── config/
│       ├── tests/
│       └── README.md
├── Core/                              # Canonical Swarm SDK code
│   ├── src/swarm_sdk/                 # Preserve the `swarm_sdk` import name
│   ├── tests/                         # SDK unit tests
│   └── pyproject.toml                 # SDK package metadata if split is needed
├── packages/                          # Reusable non-SDK libraries and integrations
│   ├── websearch/
│   │   ├── src/websearch/               # Provider fan-out, fetch, crawl, extraction
│   │   ├── tests/
│   │   └── README.md
│   ├── mcp/                            # Shared MCP client/server adapters
│   │   ├── src/swarm_mcp/
│   │   ├── tests/
│   │   └── README.md
│   ├── webscraper/                     # Only if distinct from websearch
│   │   ├── src/webscraper/
│   │   ├── tests/
│   │   └── README.md
├── agents/                              # Agent definitions and coordination
│   ├── roles/<role>/                    # Contract and manifest per role
│   ├── coordination.yaml                # Dependency and handoff graph
│   ├── benchmark/                       # Agent evaluation harness and tasks
│   └── README.md
├── shared/
│   ├── config/
│   │   ├── schemas/                     # Validation schemas, no secret values
│   │   └── README.md                    # Config precedence and ownership
│   └── resources/                       # Small source-controlled shared assets
├── tooling/
│   ├── cli/                             # Project-owned command-line tools
│   ├── scripts/                         # Development, release, and maintenance scripts
│   └── containers/                      # Dockerfiles and compose definitions
├── tests/integration/                   # Cross-package/product contract tests
├── docs/                                # Architecture, guides, decisions, migration plans
├── .github/                             # Repository-wide CI and templates
├── pyproject.toml                       # Workspace, shared dev dependencies and tooling
└── uv.lock
```

Each product/package is an ownership boundary, not a required microservice.
Keep deployable entry points and container definitions with the owner that
uses them; `tooling/containers/` is for shared development/test infrastructure.
If a product does not need a separate Python distribution, use its own
`src/<package_name>/` directory and workspace project metadata without adding
an extra runtime service.

`Core/` is the canonical home for all `swarm_sdk` code. Preserve the Python
import name `swarm_sdk`; do not keep a second SDK tree under `packages/`. Do not
create a root `Models/` folder: provider selection and model adapters belong in
`Core/src/swarm_sdk/models/`. Trained model files or model assets, if
introduced, belong under a product/package-owned `assets/models/` directory
and should not be checked in without an explicit artifact policy. Use
lowercase names for newly created subfolders unless an existing public path
requires otherwise.

## Current-to-future ownership map

| Current path or lane | Future home | Migration rule |
| --- | --- | --- |
| `src/swarm_sdk/` | `Core/src/swarm_sdk/` | Keep the import name `swarm_sdk`; move only after workspace build, tests, and tooling work. |
| `Agents/<Role>/` | `agents/roles/<role>/` | Keep each role contract and manifest together; preserve validation and discovery behavior. |
| `Agents/coordination.yaml` | `agents/coordination.yaml` | Update all runtime and validator paths atomically. |
| `Agents/benchmark/` | `agents/benchmark/` | Keep agent evaluation tasks with the agent system; SDK unit tests belong to the SDK. |
| `Main/config/` | `shared/config/` | Select one canonical config tree and document precedence; compatibility paths only when required. |
| `Newsletter/` | `products/newsletter/` | Move product-owned code/config/tests/docs together. |
| `TechNews/` | `products/technews/` | Move product-owned code/config/tests/docs together. |
| `Prediction/` | `products/prediction/` plus reusable forecasting package if needed | Split generic forecasting components from product flows before moving. |
| BotDeal lane (`Tools/BotDeal` or `Prediction/BotDeal`) | `products/botdeal/` | Reconcile both trees and assign every file exactly once. |
| NSFW lane (`Modules/NSFW` or `NSFW`) | `products/nsfw/` | Confirm product scope and owning branch before migration. |
| `WebSearch/` | `packages/websearch/` | Keep provider fan-out, fetch/crawl, extraction, and package tests together. |
| WebScraper lane (`Tools/WebScraper`) | `packages/webscraper/` or `packages/websearch/` | Compare APIs/content; merge unique behavior into WebSearch if it is not independently reusable. |
| MCP lane (`Tools/MCP`) | `packages/mcp/` | Reconcile renamed history and keep unique MCP adapters once. |
| `CLI/` | `tooling/cli/` | Move project-owned code only; keep external submodules distinct. |
| `scripts/`, `docker/` | `tooling/scripts/`, `tooling/containers/` | Update CI, docs, and invocations in the same migration. |
| Root tests | Package/product-local tests plus `tests/integration/` | Unit tests follow their owner; root tests cover cross-boundary behavior only. |
| `.cursor/`, `.github/`, `.vscode/`, `docs/` | root | Repository-wide policy, CI, editor configuration, and documentation stay centralized. |

Lane paths above describe worktree history and may not exist in the current
root checkout. Inspect the active branch trees before applying any mapping.

## Tracked folder inventory across active worktrees

This inventory was generated from tracked `HEAD` trees for the active worktrees
on 2026-10-14. It lists source/product directories and the meaningful
subfolders beneath them; Git metadata, caches, virtual environments, and
untracked local files are excluded. A path listed under a lane is not
necessarily present in the root checkout.

### SDK and integration base (`feat/ab-cache-perf`, `main`)

```text
Agents/
├── <role>/                         # One directory per specialist role
│   ├── Benchmarks/                 # Role-specific evaluations (where present)
│   └── references/                 # Supporting role material (where present)
├── _shared/
├── benchmark/
│   ├── Scripts/
│   ├── Tasks/                      # Evals, cache, GPU, RAG, SQL, routing, etc.
│   ├── model_delegation/
│   ├── sql_pro/fixtures/
│   └── tests/
└── math/algorithms/
CLI/
├── docs/superpowers/plans/
├── mcp-xeon-server/src/
└── scratch/adapter-src/
Main/{config,embeddings,vectorstore}/
Newsletter/                         # Product root; no tracked child dirs in this tip
Prediction/
├── BotDeal/
├── Database/{September,October}/DAY*/
├── graphs/
├── results/{price_multisite,rtx_forecast_2026-10-06}/
└── src/langgraph_swarm_sdk/
WebSearch/{backend,frontend,midend}/
docs/{archive/merge-backup,epics,superpowers/{plans,specs}}/
src/swarm_sdk/
├── agents/config/  commands/  config/  core/
├── execution/  gpu/  math/  memory/  models/  observability/
├── orchestrator/  pb/  prediction/  prompting/  retrieval/
├── search/  server/  serving/  tuning/
└── (package root)
```

The active `main` integration tip currently has the same tracked directory
shape as `feat/ab-cache-perf`; it also has in-progress merge changes in its
worktree. The inventory describes its committed `HEAD`, not staged merge
content.

### Specialist agents (`Agents` worktree)

```text
Agents/
├── <role>/                         # Role contract/manifests
│   ├── Benchmarks/                 # Role-specific benchmark records (where present)
│   └── references/                 # ModelDelegate references
├── antigravity-imported/<role>/    # Imported role definitions
├── _shared/
├── benchmark/
│   ├── Scripts/
│   ├── Tasks/                      # Evaluation, cache, GPU, RAG, SQL, routing, etc.
│   ├── model_delegation/
│   ├── sql_pro/fixtures/
│   └── tests/
└── math/{Benchmarks,algorithms}/
```

This lane also contains `Main/{config,embeddings,vectorstore}/`,
`src/swarm_sdk/` (including `execution/`, `runtime/`, `gpu/`, `math/`,
`memory/`, `models/`, `observability/`, `orchestrator/`, `prompting/`,
`retrieval/`, `serving/`, and related SDK packages), `tests/`, `scripts/`,
`codeworkspace/`, and documentation directories. Treat these as inherited base
content rather than ownership by the Agents product lane.

### Newsletter product lane (`newsletter` worktree)

```text
Documents/
Main/{config,embeddings,vectorstore}/
Newsletter/
deep-research/
docker/
docs/superpowers/{plans,specs}/
notebooks/
scripts/
src/swarm_sdk/                       # Inherited SDK checkout content
tests/
```

The `Newsletter/` directory itself has no tracked nested directory in this
branch tip. Preserve the distinction between the product folder and inherited
SDK source when assigning future ownership.

### NSFW lane (`NSFW` worktree)

This is a full SDK checkout with the base `Agents/`, `Main/`, `Newsletter/`,
`Prediction/`, `WebSearch/`, `src/swarm_sdk/`, `tests/`, `docs/`, and tooling
trees, plus:

```text
rust/websearch-rs/{.cargo,src}/
scratch/
scripts/mcp-wrappers/
```

The worktree name alone does not prove that all inherited paths belong to the
NSFW product. Identify the NSFW-specific files before moving them to
`products/nsfw/`.

### TechNews product lane (`TechNews` worktree)

```text
TechNews/
├── src/technews/
│   ├── prediction/
│   └── scrape/
└── tests/
```

This is the clearest existing product-style source layout among the lanes.
The proposed destination is `products/technews/`, retaining these internal
boundaries unless implementation review supports a change.

### OpenCL refactor lane (`refactor/shared-opencl-helpers` worktree)

This lane carries the SDK base plus:

```text
rust/websearch-rs/{.cargo,src}/
scratch/
scripts/mcp-wrappers/
```

Its ownership is limited to the shared OpenCL changes; inherited product and
integration directories should not be assigned to this lane.

### BotDeal lane (`BotDeal` worktree)

```text
Database/{April,August,December,February,January,July,June,March,May,November,October,September}/
Main/{config,embeddings,vectorstore}/
Prediction/BotDeal/
```

The branch has both root `Database/` month partitions and
`Prediction/BotDeal/`; compare these with other BotDeal copies and determine
which data is source-controlled product input versus generated output before
choosing the final `products/botdeal/` children.

### MCP lane (`feat/proxy-routing` worktree; proxy-routing feature excluded)

```text
MCP/{backups,crawl4ai,economizer,pgvector,scripts,tests}/
Main/{config,embeddings,vectorstore}/
WebSearch/{backend,frontend,midend}/
rust/websearch-rs/{.cargo,src}/
scripts/mcp-wrappers/
src/swarm_sdk/                       # Inherited SDK checkout content
```

The proxy-routing feature from this lane is excluded from the target. The
`MCP/backups/` directory needs explicit review before any future move; do not
treat backup trees as canonical implementation. Retain MCP functionality only
when it is independently needed and reviewed, grouped under one MCP package.

### Model Gateway lane (`feat/model-gateway` worktree; feature excluded)

The Model Gateway feature is excluded from the target. Its merge commit is
already present in the isolated integration history and must be reverted there
as part of `Mergeplan.md` before the integration is considered complete.

### Prediction lane (`Prediction` worktree)

```text
Prediction/
├── BotDeal/
├── Database/{September,October}/DAY*/
├── graphs/
└── results/{price_multisite,rtx_forecast_2026-10-06}/
```

This tip also carries SDK and Rust WebSearch base content. Keep forecast
algorithm/library code separate from BotDeal-specific forecasting flows and
from generated result directories in the future product/package split.

### WebScraper lane (`WebScraper` worktree)

```text
WebScraper/
├── crawl4ai/
├── pgvector/
├── scripts/
└── searxng/
Main/{config,embeddings,vectorstore}/
rust/websearch-rs/{.cargo,src}/
scripts/mcp-wrappers/
src/swarm_sdk/                       # Inherited SDK checkout content
```

Compare `WebScraper/{crawl4ai,pgvector,searxng}` with MCP adapter directories
and `WebSearch/{frontend,midend,backend}` before assigning the canonical
package. Keep one implementation of shared crawl, search, and vector-store
adapters.

### WebSearch lane (`Websearch` worktree)

```text
WebSearch/
├── backend/
├── benchmarks/
├── configs/vane-searxng/
├── frontend/
├── midend/
└── tests/
compat/ormsgpack-orjson/ormsgpack/
scratch/merge-backup/
scripts/mcp-wrappers/
src/swarm_sdk/                       # Inherited SDK checkout content
```

Treat `compat/` and `scratch/merge-backup/` as compatibility/archive areas to
review, not automatic future runtime packages. WebSearch module tests should
move with the canonical WebSearch package.

### Folder disposition rules

- `Database/`, `results/`, `scratch/`, `backups/`, and `compat/` require
  classification as source, fixture, generated output, backup, or compatibility
  shim before migration.
- `src/swarm_sdk/` repeated across lane worktrees is shared base code, not
  multiple SDK packages. Merge SDK changes by Git history into one `Core/`
  tree.
- `Main/` repeated across worktrees should become one shared config/resource
  owner; preserve symlink targets and consumers during migration.
- A subfolder shown only in one lane is not presumed to be unique or canonical;
  compare path and content inventories before copying or deleting it.

## Directory boundaries

- **Product**: user-facing behavior, product configuration, entry points, and
  product-owned tests. Products depend on packages; packages do not import
  product internals.
- **Package**: reusable SDKs and integrations with a stable API. A package owns
  its source, dependency declarations where practical, and unit tests.
- **Agents**: orchestration persona contracts and manifests. Agent definitions
  may call packages and products through declared interfaces, not duplicate
  their implementations.
- **Shared**: configuration schemas and resources used by multiple owners.
  Keep runtime behavior out of this folder.
- **Tooling**: repository development and deployment utilities, not runtime
  product code.

## Migration phases

### 1. Establish ownership and baseline

- Inventory every active branch/worktree, dirty path, root directory, package
  entry point, test, config reference, and CI path.
- Assign every directory and file to one owner. Mark exact duplicates, renamed
  paths, and same-name files with different content separately.
- Preserve all dirty worktree changes. Integrate committed tips only, and keep
  a record of source branch and commit for each imported lane.
- Resolve the branch merge and establish a green or explicitly documented
  baseline before moving directories.

### 2. Reconcile duplicate and overlapping modules

- Choose canonical owners for BotDeal, WebScraper/WebSearch, and MCP from
  content and import relationships, not folder names alone.
- Merge unique files and behavior into the chosen owner; do not copy whole
  trees when only some files are unique.
- Update imports, entry points, tests, CI, docs, and config paths together.
- Verify there are no duplicate package trees or ambiguous import roots.

### 3. Create a workspace-compatible package structure

- Configure the Python workspace and package discovery before moving source.
- Move `swarm_sdk` into `Core/` only after editable installs, `uv`, LangGraph graph paths,
  protobuf generation, and all test commands work from the new location.
- Move reusable integrations into `packages/`; retain their public import names
  or provide a deliberate, time-bounded migration path.
- Move product directories into `products/` one at a time, preserving product
  entry points and deployment configuration.

### 4. Centralize shared assets and tooling

- Consolidate configuration into `shared/config/` with one source of truth and
  explicit compatibility handling for old paths.
- Rehome scripts, Docker assets, and project-owned CLI code under `tooling/`.
- Keep repository policy, CI workflows, docs, and editor settings at the root.

### 5. Validate and remove obsolete paths

- For each move, run focused tests, import checks, lint/type checks, and the
  relevant package or product build.
- Search for old path references in code, YAML, TOML, JSON, shell scripts,
  workflows, docs, and dynamic import strings.
- Remove an old path only after all references are migrated and the owning
  tests pass. Check the final tree for duplicate file contents and directories.
- Update `README.md`, `AGENTS.md`, `docs/LAYOUT.md`, workspace files, and CI
  path filters to match the resulting tree.

## Completion criteria

- Each product, package, configuration set, and integration has one declared
  owner and one canonical source tree.
- No duplicate module trees remain from branch merges; intentional fixtures,
  generated files, vendor trees, and historical docs are documented exceptions.
- Package imports and documented CLI commands work from the workspace root.
- CI, developer commands, templates, deployment manifests, and docs refer to
  the new canonical paths.
- Dirty source worktrees were preserved, and every integrated committed tip is
  traceable in Git history.

## Current checkout reference

For the present root layout, see [`docs/LAYOUT.md`](docs/LAYOUT.md) and
[`AGENTS.md`](AGENTS.md). This plan does not itself move directories or merge
branches.
