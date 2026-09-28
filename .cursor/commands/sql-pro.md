---
description: Run the SQL Pro benchmarkable suite (correctness, EXPLAIN plans, index checks)
---

# /sql-pro — Benchmarkable suite

Use the attached **sql-pro** skill for query design and optimization context. This command runs the repo’s **benchmarkable** SQL suite (no API keys).

## Run

```bash
uv run python -m benchmark.sql_pro.run
uv run python -m benchmark.sql_pro.run --json
uv run python -m benchmark.sql_pro.run --case covering_index_customer_orders
uv run pytest benchmark/Tasks/sql_pro -q
```

## What it measures

| Case | SQL Pro workflow step |
|------
------------------------|
| `window_latest_completed_order` | CTE + window functions, filter early |
| `join_vs_correlated_subquery` | Set-based join vs correlated subquery equivalence |
| `covering_index_customer_orders` | Composite index + `EXPLAIN QUERY PLAN` (SEARCH vs SCAN) |
| `exists_active_orders` | `EXISTS` for existence checks |

## After a run

1. For failures, print the case `explain_plan` and align with sql-pro **Verify** (EXPLAIN / plan analysis).
2. Edit cases in `benchmark/sql_pro/suite.yaml` or seed logic in `benchmark/sql_pro/harness.py`.
3. Optional artifacts: `benchmark/results/sql_pro/` (gitignored).

## Extend

Add a case to `suite.yaml`, mirror its `id` in `test_sql_pro_suite.py` parametrize list, and re-run pytest.
