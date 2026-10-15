# Implementation Plan: Swarm Database and Persistence Refactor

## Overview

Refactor persistence in the Swarm SDK and its product code so every store has a
clear owner, durability contract, lifecycle, schema policy, and configuration
path. Keep vector memory, response caching, LangGraph checkpoints, remote or
in-memory vector adapters, and BotDeal's Parquet product data as distinct
domains. The destination layout follows the repository's existing future-state
plan: the one SDK tree moves from the current `src/swarm_sdk/` location to
`Core/src/swarm_sdk/`, and product code/data stay under product ownership. The
broader refactor plan owns those directory moves. Until its integration
checkpoint, implementation tasks in this plan target the current source paths;
`Core/` paths describe the approved destination. Do not move folders or alter
stored data until branch integration and ownership review are complete.

This plan expands the persistence portion of `RefactorPlan.md` Task 3.2. It does
not replace that broader codebase refactor or the branch integration steps in
`Mergeplan.md`.

## Current Findings

- SQLite vector memory lives in `src/swarm_sdk/memory/sqlite_vec.py`; it has a
  sqlite-vec extension path and an INT8 BLOB fallback, plus optional FTS5.
- `SemanticCache` in `src/swarm_sdk/retrieval/cache.py` owns exact and semantic
  SQLite tables, ad-hoc compatibility `ALTER TABLE` upgrades, WAL settings,
  locking, TTL/LRU behavior, and an optional Redis exact-cache layer.
- `src/swarm_sdk/core/checkpoint.py` opens LangGraph's SQLite saver directly;
  LangGraph owns the checkpoint schema.
- FAISS and OpenCL memory stores are process-local. Mem0 is an external service
  adapter. `QdrantStore` currently constructs `QdrantClient(path=...)`, so its
  implementation is local embedded storage despite its remote-host description.
- `Prediction/BotDeal/database.py` is a product-owned Polars/Parquet store, not
  SQL. Historical product data exists under `Prediction/Database/`; other
  worktree tips may contain additional root `Database/` partitions. The merge
  and codebase plans require classifying those files before migration.
- The common memory protocol does not currently express store closure or
  persistence capabilities. SQLite stores expose `close()` independently.
- `Main/vectorstore/` is a compatibility re-export of SDK memory types.
- Coder task `DB01` added coverage that the SQLite INT8 fallback can append
  after reopening and preserves sequential IDs; retain it in the focused
  storage suite.

## Architecture Decisions

- Use `Core/` as the only Swarm SDK root. The database refactor follows the
  SDK's existing domain boundaries there:

  ```text
  Core/src/swarm_sdk/
  ├── storage/              # Shared SQLite mechanics only, if justified
  ├── memory/               # Vector-memory API and backend adapters
  ├── retrieval/cache.py    # Exact and semantic response-cache policy/data
  └── core/checkpoint.py   # LangGraph saver selection and path lifecycle

  products/botdeal/         # Product-owned Parquet storage and data
  ```

  `storage/` is not a destination for every database implementation. Cache,
  vector-memory, checkpoint, and product schemas stay owned by their domains.
- Preserve separate storage domains and their public behavior. Do not create a
  generic repository/ORM layer or move all persistence into one monolithic
  `database.py`.
- Add shared SQLite utilities only for behavior that is demonstrably repeated
  and has identical semantics (path expansion/parent creation, safe connection
  setup, and lifecycle). Store-specific schemas, transactions, indexes, and
  query code remain with their owning cache, memory, or checkpoint subsystem.
- Version schemas per SQLite database owner. Use explicit, ordered migrations
  for SDK-owned vector-memory and response-cache schemas. Do not migrate or
  rewrite LangGraph's saver schema; defer to its supported saver API.
- Make backend durability and capabilities explicit: persistent/local,
  process-local/volatile, or external/remote. Keep optional backends lazy.
- Keep BotDeal Parquet storage and product data outside the SDK storage layer.
  Relocate it only with the product move in the broader codebase plan.
- Preserve public import paths with temporary re-exports when files move into
  `Core/`; remove compatibility paths only after imports and docs are migrated.
- Keep user databases and historical Parquet files intact. Any conversion or
  relocation requires a separate, reviewed backup and rollback procedure.

## Task List

### Phase 1: Establish ownership and contracts

#### Task 1: Inventory database files, data, and references

**Description:** Record tracked database-related source, configs, tests, local
data paths, active worktree copies, and every runtime path/import reference.
Classify each artifact as source code, schema, fixture, generated data, user
data, cache, checkpoint, or archived copy. Do not read secrets or rewrite data.

**Acceptance criteria:**
- [ ] Every persistence implementation and data tree has one proposed owner.
- [ ] Duplicate and same-name/different-content paths are reported separately.
- [ ] Local ignored databases and Parquet data have a documented preservation
  boundary and are excluded from destructive cleanup.

**Verification:** Compare `git ls-files` inventories across active worktrees;
search imports/config/docs with `rg`; compare file hashes only for regular,
non-sensitive tracked artifacts; review the inventory against `Codebase.md` and
`Mergeplan.md`.

**Dependencies:** Mergeplan baseline and active-worktree inventory.

**Files likely touched:** `tasks/plan.md`, `Codebase.md` (inventory update only
if the ownership map changes).

**Estimated scope:** Small.

#### Task 2: Specify persistence contracts and backend capability matrix

**Description:** Document API behavior, ID semantics, vector score semantics,
durability, concurrency/thread behavior, tenant isolation, optional dependency
loading, and close semantics for each memory, cache, checkpoint, and product
store. Resolve the mismatch between Qdrant's description and local `path=`
construction before changing its configuration surface.

**Acceptance criteria:**
- [ ] A capability table distinguishes persistent, volatile, and external
  backends and states whether each supports vector, text, or exact lookup.
- [ ] Current behavior for cache keys, TTL, tenant isolation, ranking, IDs,
  error handling, and default paths is captured as compatibility contracts.
- [ ] Unknown or behavior-changing decisions are marked as open questions,
  rather than silently chosen during implementation.

**Verification:** Cross-check the table against constructors, settings, config
loader, factories, and focused tests for each adapter.

**Dependencies:** Task 1.

**Files likely touched:** `docs/` persistence design note, `tasks/plan.md`.

**Estimated scope:** Medium.

### Checkpoint A: Design review

- [ ] Review the ownership inventory and capability matrix before changing
  storage APIs, schemas, or directory layout.
- [ ] Confirm branch integration is stable and no active worktree's dirty data
  or code will be overwritten.

### Phase 2: Define a safe persistence foundation

#### Task 3: Decide and specify the narrow SQLite utility boundary

**Description:** Determine whether a shared helper is warranted for repeated
connection setup and lifecycle. Specify exact behavior for path expansion,
parent creation, timeout, WAL/synchronous settings, transaction ownership,
thread checks, and close. Leave owner-specific PRAGMAs and transaction policies
local when requirements differ.

**Acceptance criteria:**
- [ ] A small interface and ownership diagram distinguish shared connection
  mechanics from store-owned schema/query logic.
- [ ] No generic ORM, repository abstraction, or cross-backend lowest-common-
  denominator API is introduced.
- [ ] If no safe common behavior exists, the plan explicitly keeps connection
  setup local and records the reason.

**Verification:** Review current SQLite connection call sites in memory,
retrieval cache, and checkpoint code; compare their required settings and
threading behavior.

**Dependencies:** Task 2.

**Files likely touched:** `docs/` persistence design note; optionally
`src/swarm_sdk/storage/` only if the review proves a shared helper is warranted
(it moves with the SDK in the broader Core layout task).

**Estimated scope:** Small.

#### Task 4: Define schema versioning, migration, backup, and rollback rules

**Description:** Design independent migration histories for SDK-owned SQLite
files. Treat existing cache tables and sqlite-vec/fallback table combinations
as legacy states that must be detected and migrated without dropping data.
Exclude LangGraph's internal schema and BotDeal Parquet transformations.

**Acceptance criteria:**
- [ ] Supported legacy states and target schema versions are listed for
  vector memory and response cache.
- [ ] Migrations are ordered, transactional when SQLite permits, idempotent,
  and fail closed on unsupported/newer schemas.
- [ ] Backup, restore, interruption, and rollback behavior is specified before
  any migration is applied to a user database.

**Verification:** Review migration plans against existing table creation and
`ALTER TABLE` paths; exercise migration fixtures on temporary copies in the
implementation phase; prove original fixtures/data are unchanged on failure.

**Dependencies:** Tasks 1–3.

**Files likely touched:** `docs/` persistence design note and per-store
migration modules under the current `src/swarm_sdk/` tree. Use
`aivana-database-engineer:ai-migration-risk-radar` and
`aivana-database-engineer:ai-data-contract-guardian` as review aids when their
inputs apply; their output does not replace disposable-copy migration tests.

**Estimated scope:** Medium.

### Phase 3: Refactor by persistence owner

#### Task 5: Version and isolate the SQLite vector-memory schema

**Description:** Refactor `SqliteVecStore` schema creation and compatibility
handling into a store-owned migration boundary. Preserve sqlite-vec and INT8
fallback data, optional FTS5 behavior, ranking, IDs, and current public imports.

**Acceptance criteria:**
- [ ] A fresh store and every supported legacy schema open with the same public
  API and expected search behavior.
- [ ] Existing vector rows remain visible across extension-enabled and
  fallback-mode compatibility checks; unsupported incompatible storage fails
  with a clear diagnostic.
- [ ] Store lifecycle is explicit and safe for repeated close or documented
  as single-close if idempotence cannot be guaranteed.

**Verification:** Focused `SqliteVecStore` persistence, fallback, keyword,
dimension, ranking, reopen, and lifecycle tests using temporary databases.

**Dependencies:** Tasks 3–4.

**Files likely touched:** `src/swarm_sdk/memory/sqlite_vec.py`, a
store-owned migration helper, and focused memory tests.

**Estimated scope:** Medium.

#### Task 6: Version and isolate response-cache storage

**Description:** Replace constructor-time ad-hoc schema upgrades with explicit
cache-owned migrations. Preserve exact/semantic cache behavior, cache key
serialization, tenant scoping, TTL/LRU pruning, batching, WAL durability
expectations, and Redis fail-open semantics.

**Acceptance criteria:**
- [ ] Existing cache schemas migrate without losing entries or tenant identity.
- [ ] Exact and semantic lookups, TTL/LRU eviction, multiple SQLite instances,
  and optional Redis behavior remain contract-compatible.
- [ ] SQLite and Redis lifecycle/error boundaries are explicit; Redis remains an
  optional exact-cache layer rather than silently becoming the source of truth.

**Verification:** Focused cache migration, multi-instance, tenant-isolation,
TTL/LRU, serialization, and Redis fake-client tests.

**Dependencies:** Tasks 3–4.

**Files likely touched:** `src/swarm_sdk/retrieval/cache.py`,
`src/swarm_sdk/retrieval/redis_exact.py`, a cache migration helper, and focused
cache tests.

**Estimated scope:** Medium.

#### Task 7: Correct the Qdrant storage contract

**Description:** Resolve the mismatch between Qdrant's remote-host description
and current local `QdrantClient(path=...)` construction. Decide whether to keep
the local mode, add a separately configured remote mode, or support both. Do
not silently reinterpret existing `memory_path` values.

**Acceptance criteria:**
- [ ] The implementation and configuration unambiguously distinguish local
  embedded and remote Qdrant modes, or document the deliberate single mode.
- [ ] Existing `memory_path` configuration retains its current meaning until
  an explicit compatibility migration is approved.
- [ ] The Qdrant extra remains lazy, and missing-dependency errors remain
  actionable.

**Verification:** Focused Qdrant factory/config tests with fakes and import
checks with the optional dependency absent.

**Dependencies:** Task 2.

**Files likely touched:** `src/swarm_sdk/memory/qdrant_store.py`,
`src/swarm_sdk/config/settings.py`, `src/swarm_sdk/config/loader.py`,
`src/swarm_sdk/core/factories.py`, and Qdrant factory/config tests.

**Estimated scope:** Medium.

#### Task 8: Document volatile and external memory backends

**Description:** Align FAISS, OpenCL, and Mem0 documentation with their actual
process-local or externally managed persistence. Decide whether lifecycle
methods belong in the public `MemoryStore` protocol; keep them optional unless
all supported adapters can implement a meaningful, consistent contract.

**Acceptance criteria:**
- [ ] FAISS and OpenCL are identified as volatile and Mem0 as externally
  managed; local file durability is not implied for these adapters.
- [ ] Backend selection remains lazy and optional dependency errors remain
  actionable.
- [ ] No backend or existing data is silently switched as part of documenting
  its persistence semantics.

**Verification:** Focused backend contract tests and import checks with each
optional dependency absent; review documentation against the constructors.

**Dependencies:** Task 2.

**Files likely touched:** `src/swarm_sdk/memory/faiss_store.py`,
`src/swarm_sdk/memory/opencl_store.py`, `src/swarm_sdk/memory/mem0_store.py`,
backend tests, and storage docs.

**Estimated scope:** Medium.

#### Task 9: Keep LangGraph checkpoint persistence under saver ownership

**Description:** Review checkpoint path handling and lifecycle without taking
ownership of LangGraph's schema. Add only the minimum wrapper needed for
directory creation, saver selection, and resource closure supported by the
installed LangGraph saver API.

**Acceptance criteria:**
- [ ] `None` continues to select in-memory checkpointing and configured paths
  continue to select durable SQLite checkpointing.
- [ ] No custom DDL or migration touches LangGraph-managed tables.
- [ ] Thread ID persistence and server-injected checkpointer behavior remain
  unchanged.

**Verification:** Focused checkpoint lifecycle/reopen tests and graph tests
using both SDK-owned and externally injected saver paths.

**Dependencies:** Task 2.

**Files likely touched:** `src/swarm_sdk/core/checkpoint.py`,
`src/swarm_sdk/core/swarm.py`, and checkpoint/graph tests.

**Estimated scope:** Medium.

#### Task 10: Keep BotDeal Parquet storage within product ownership

**Description:** Treat `Prediction/BotDeal/database.py` and
`Prediction/Database/` as product data/storage, not SDK database code. Identify
which Parquet files are canonical input, generated output, or historical data;
then coordinate any code/data move with the BotDeal merge and product-layout
plan.

**Acceptance criteria:**
- [ ] Every Parquet tree has an owner, retention purpose, and migration status.
- [ ] Product records remain schema-validated and deduplicated by the existing
  `(url, observed_at)` key unless an explicit product decision changes it.
- [ ] Data relocation is reversible and verifies record counts and schema
  compatibility; no data is deleted as part of an SDK refactor.

**Verification:** Product database tests on temporary roots; read-only
inventory and checksums for source data; compare row counts, columns, and
deduplication outcomes after any future migration.

**Dependencies:** Task 1 and the BotDeal ownership decision in `Mergeplan.md`.

**Files likely touched:** `products/botdeal/` after that product move,
`Prediction/BotDeal/database.py`, BotDeal tests and product docs.

**Estimated scope:** Medium.

### Checkpoint B: Persistence behavior preserved

- [ ] Focused storage tests pass for all changed owners.
- [ ] Migration tests cover fresh, supported legacy, interrupted, and
  unsupported-newer schema cases.
- [ ] Public imports, config paths, default backend, and serialized cache keys
  remain compatible or have an explicitly approved migration.

### Phase 4: Document and hand off to the canonical layout plan

The branch integration plan owns merge order. The broader refactor plan owns
moving the SDK package to `Core/` and moving product code/data to approved
product paths; this plan does not duplicate those directory-move tasks.

#### Task 11: Update persistence documentation and operational guidance

**Description:** Document ownership, backend capabilities, default paths,
backup/restore, schema upgrade behavior, optional dependencies, and the
distinction between cache, memory, checkpoints, and product data.

**Acceptance criteria:**
- [ ] README/config docs describe actual durability and backend behavior.
- [ ] Migration and rollback instructions identify supported legacy schemas
  and how to preserve local data.
- [ ] `Codebase.md` and the broader refactor plan link to the canonical
  persistence map without duplicating the detailed design.

**Verification:** Follow every documented command/path from the repo root and
check links and config examples against current schemas.

**Dependencies:** Tasks 5–10. Update canonical destination links when the
broader `RefactorPlan.md` Core/product move reaches its path-migration step.

**Files likely touched:** `README.md`, `docs/`, `Codebase.md`,
`RefactorPlan.md`.

**Estimated scope:** Medium.

### Checkpoint C: Persistence refactor complete

- [ ] All focused storage tests and the repository quality gate pass.
- [ ] No unexpected duplicate persistence implementations or stale database
  references remain in the current integrated tree.
- [ ] All user-owned local database and product data is preserved and
  accounted for.
- [ ] Human review approves the API, migration, and ownership decisions before
  production data or the broader directory layout is changed.

## Risks and Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Existing SQLite schemas are upgraded implicitly in constructors | Data loss or startup failure | Inventory legacy states; add explicit migrations and test on copied temporary databases before production paths. |
| sqlite-vec availability differs by Python build | Existing vectors may become unreadable | Preserve both extension and INT8 fallback schemas; fail with a clear error rather than hiding rows. |
| Shared connection helpers flatten different transaction/PRAGMA requirements | Lock contention or durability regression | Share only identical connection mechanics; keep owner-specific policy local. |
| Backend labels overstate durability or remote behavior | Data unexpectedly disappears or is stored locally | Publish capability matrix; do not reinterpret config/path values without an explicit migration. |
| LangGraph saver internals change | Checkpoints become unreadable | Keep schema ownership with LangGraph and test only supported saver APIs. |
| Branch merges contain duplicate or divergent Parquet files | Wrong product data is selected or overwritten | Reconcile tracked files by branch/content and classify before moves; preserve originals and hashes. |
| Moving SDK and product paths breaks imports and deployment paths | Runtime/import failures | Coordinate with the existing workspace migration plan; move one owner at a time with compatibility re-exports and path searches. |

## Open Questions

- Should Qdrant support only its current local embedded path, or should the
  SDK expose a separately configured remote URL mode? Preserve today's meaning
  until decided.
- Which `Prediction/Database/` and root `Database/` Parquet files are canonical
  product input, generated snapshots, or historical records across all active
  worktrees?
- Should the memory-store protocol require `close()` or context-manager
  support, or should lifecycle remain an optional capability for volatile and
  externally managed stores?
- Should the SQLite vector store and response cache share only a low-level
  connection/path utility, or should duplicated setup stay local for clarity?

## Task List Index

The ordered implementation checklist and checkpoints are tracked in
[`tasks/todo.md`](todo.md). This persistence plan is subordinate to the branch
integration and workspace-layout decisions in `Mergeplan.md` and
`RefactorPlan.md`. The broader refactor plan owns moving the one SDK tree to
`Core/src/swarm_sdk/` and product code/data to approved owners; this plan does
not duplicate those moves or introduce a monolithic SDK `Database/` subtree.
