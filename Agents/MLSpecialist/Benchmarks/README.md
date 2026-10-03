# Benchmarks — MLSpecialist

Role-specific benchmark notes, case IDs, and expected deltas for **MLSpecialist**.

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
- Hand measurement work to Optimizer / MLSpecialist when the task is pure perf or model eval; keep this folder for MLSpecialist-owned acceptance checks.

## Python runtime & numerics (shared harnesses)

| Task | When MLSpecialist owns it | Command |
| :--- | :--- | :--- |
| [`python315_claims`](../../benchmark/Tasks/python315_claims/) | Validating §11.2 claims vs this host | `uv run --extra dev python -m benchmark.Tasks.python315_claims.benchmark_python315_claims --write-results` |
| [`cold_import`](../../benchmark/Tasks/cold_import/) | SDK import-time / lazy-import stack | `PYTHONPATH=Agents uv run python -m benchmark.Tasks.cold_import.benchmark_cold_import` |
| [`gpu_retrieval`](../../benchmark/Tasks/gpu_retrieval/) | OpenCL vs NumPy vector search | See [`benchmark/README.md`](../../benchmark/README.md) § bounded retrieval |
| [`gpu_quantization`](../../benchmark/Tasks/gpu_quantization/) | INT8 / quant paths | `uv run python Agents/benchmark/Tasks/gpu_quantization/benchmark_gpu_quantization.py` |

Dossier cross-reference: `Documents/Python3.15.md` §11.3 and `~/Documentos/Python3.15.md` (mirror).
