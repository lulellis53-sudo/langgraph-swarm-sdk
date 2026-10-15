# Database Refactor Task List

Detailed scope, acceptance criteria, dependencies, and verification commands
are in [`plan.md`](plan.md).

## Phase 1: Establish ownership and contracts

- [ ] Task 1: Inventory database files, data, and references.
- [ ] Task 2: Specify persistence contracts and backend capability matrix.

### Checkpoint A: Design review

- [ ] Review ownership inventory and capability matrix.
- [ ] Confirm branch integration is stable and dirty worktrees are preserved.

## Phase 2: Define a safe persistence foundation

- [ ] Task 3: Decide and specify the narrow SQLite utility boundary.
- [ ] Task 4: Define schema versioning, migration, backup, and rollback rules.

## Phase 3: Refactor by persistence owner

- [ ] Task 5: Version and isolate the SQLite vector-memory schema.
- [ ] Task 6: Version and isolate response-cache storage.
- [ ] Task 7: Correct the Qdrant storage contract.
- [ ] Task 8: Document volatile and external memory backends.
- [ ] Task 9: Keep LangGraph checkpoint persistence under saver ownership.
- [ ] Task 10: Keep BotDeal Parquet storage within product ownership.

### Checkpoint B: Persistence behavior preserved

- [ ] Focused storage tests pass for each changed owner.
- [ ] Migration tests cover fresh, legacy, interrupted, and unsupported schema cases.
- [ ] Public imports, configuration, cache keys, and default behavior are compatible.

## Phase 4: Document and hand off to the canonical layout plan

- [ ] Task 11: Update persistence documentation and operational guidance.

### Checkpoint C: Completion

- [ ] Focused tests and the repository quality gate pass.
- [ ] No unexpected duplicate implementations or stale paths remain.
- [ ] Local database and product data is preserved and accounted for.
- [ ] Human review approves API, migration, and ownership changes.
