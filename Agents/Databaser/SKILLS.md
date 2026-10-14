# Databaser skill map

Use the installed `aivana-database-engineer` skills when their evidence model
fits the task. These skills provide analysis and planning support; they do not
replace the Databaser task's file scope, repository rules, or verification
requirements.

## Schema and migration work

- `aivana-database-engineer:ai-migration-risk-radar` — assess migration scope,
  blast radius, and rollback rehearsal needs before proposing a schema change.
- `aivana-database-engineer:ai-data-contract-guardian` — check an explicit data
  contract for required columns, drift, PII declarations, and retention rules.
- `aivana-database-engineer:rollback-rehearsal-engine` — structure a rollback
  rehearsal from a concrete migration and recovery target.
- `aivana-database-engineer:query-contract-tester` — validate SQL behavior
  against a supplied query contract and representative cases.

Use these against reviewed schemas and disposable copies during development.
Do not point a local code refactor at production data or execute DDL unless the
user explicitly requests and authorizes that operation.

## Query analysis and tuning

- `aivana-database-engineer:explain-query` — explain supplied query-plan
  evidence and form testable hypotheses.
- `aivana-database-engineer:ai-query-rewrite-lab` — generate analysis-only
  rewrite candidates without executing SQL.
- `aivana-database-engineer:sql-performance-advisor` — use for scoped,
  evidence-backed performance work when the relevant live or lab evidence is
  available; distinguish measured results from estimates.

## Planning and operations

- `aivana-database-engineer:objective-to-ops-plan` — translate a broad database
  objective into measurable goals, guardrails, and dry-run workflows.
- `aivana-database-engineer:autonomous-dba-copilot` — coordinate an
  evidence-gathering DBA loop for operational database questions. Do not use it
  as a substitute for source-code inspection or migration tests.

If an applicable skill or its required evidence is unavailable, state that
limitation and continue with the repository's local code/tests where possible.
