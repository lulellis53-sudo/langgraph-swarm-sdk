# Benchmarks — DevOps

Role-specific benchmark notes, case IDs, and expected deltas for **DevOps**.

Shared suite and runners: [`benchmark/`](../../benchmark/) (see [`benchmark/README.md`](../../benchmark/README.md)).

## Layout

| Path | Purpose |
|------|---------|
| `cases/` | Optional case IDs or fixtures scoped to this agent's tasks |
| `notes.md` | Methodology, commands, and acceptance thresholds |
| `results/` | Local run output only — do not commit (gitignored at repo root) |

## Conventions

- Prefer pointing at existing `benchmark/Tasks/` or `benchmark/sql_pro/` cases over duplicating harnesses.
- Document the exact command, seed, and environment for any number you record.
- Hand measurement work to Optimizer / MLSpecialist when the task is pure perf or model eval; keep this folder for DevOps-owned acceptance checks.
