---
description: Run the SQL Pro benchmarkable suite (correctness, EXPLAIN plans, index checks)
---

# /sql-pro — Benchmarkable suite

Use your personal **sql-pro** skill (Agent Store: `skills/sql-pro/`) for query design and optimization context. Enable or attach that skill in Cursor when using this command. This command runs the repo’s **benchmarkable** SQL suite (no API keys).

## Run

```bash
uv run python -m benchmark.sql_pro.run
uv run python -m benchmark.sql_pro.run --json
uv run python -m benchmark.sql_pro.run --write-results
uv run python -m benchmark.sql_pro.run --case covering_index_customer_orders
uv run pytest benchmark/Tasks/sql_pro -q
uv run python -m benchmark.run --task sql_pro
```

## What it measures

| Case | SQL Pro workflow step |
|------|------------------------|
| `window_latest_completed_order` | CTE + window functions, filter early |
| `join_vs_correlated_subquery` | Set-based join vs correlated subquery equivalence |
| `covering_index_customer_orders` | Composite index + `EXPLAIN QUERY PLAN` (SEARCH vs SCAN) |
| `exists_active_orders` | `EXISTS` for existence checks |
| `not_exists_vs_anti_join` | `NOT EXISTS` vs anti-join equivalence |
| `having_vs_filtered_subquery` | `HAVING` vs filtered subquery equivalence |
| `keyset_vs_offset` | Keyset pagination vs `OFFSET` |
| `orders_status_scan_without_index` | Status index + plan before/after |

## After a run

1. For failures, print the case `explain_plan` and align with sql-pro **Verify** (EXPLAIN / plan analysis).
2. Edit cases in `benchmark/sql_pro/suite.yaml` or seed logic in `benchmark/sql_pro/harness.py`.
3. Optional artifacts: `benchmark/results/sql_pro/` via `--write-results` (gitignored).

## Extend

Add a case to `benchmark/sql_pro/suite.yaml` (and harness support if you introduce a new case type), then re-run pytest or `python -m benchmark.sql_pro.run`. Case IDs are loaded from the suite automatically.
