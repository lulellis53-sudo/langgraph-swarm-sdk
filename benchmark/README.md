# Benchmarks

Task folders under `Tasks/{name}/` measure token usage, cache hits, retrieval quality, and swarm behavior using **predefined models** from [config/swarm.yaml](../config/swarm.yaml) and scripted chat models (no API keys in CI).

## Token-minimization pipeline (what we score)

1. Exact + semantic cache before any LLM call.
2. Router on `think_level: low` and cheapest route in `model_select.routes`.
3. Hybrid dense + BM25 recall, dedupe, rerank, inject only top-k snippets.
4. Tokenizer budget + think-level caps before prompts.
5. Parallel fan-out with JSON briefs instead of full transcripts.

## Run

```bash
uv run pytest benchmark/ -q
uv run python -m benchmark.run --task token_cache_hit
```

Results (optional): `benchmark/results/{task}/` (gitignored).

## Embedding throughput (CPU vs CoreML GPU)

Compare ONNX Runtime providers for FastEmbed (requires `uv sync --extra jupyter`):

```bash
uv run python benchmark/CPU_GPU.py
uv run python benchmark/CPU_GPU.py --write-results --json
uv run python benchmark/CPU_GPU.py --cuda   # include CUDA when available
```

## Model Delegation benchmark suite

Provider-routing and GPU-dispatch cases under `Tasks/model_delegation/`. No API keys required.

```bash
uv run pytest benchmark/Tasks/model_delegation -q
uv run python -m benchmark.run --task model_delegation
```

Case definitions: `benchmark/model_delegation/suite.yaml`.

## SQL Pro benchmarkable suite

Skill-aligned SQLite cases under `sql_pro/` (correctness, join rewrites, index plans). No LLM required.

Both `pytest benchmark/Tasks/sql_pro` and `python -m benchmark.run --task sql_pro` execute the full suite (the task module delegates to `benchmark.sql_pro.run`).

```bash
uv run python -m benchmark.sql_pro.run
uv run python -m benchmark.sql_pro.run --write-results
uv run pytest benchmark/Tasks/sql_pro -q
uv run python -m benchmark.run --task sql_pro
```

Case definitions: `benchmark/sql_pro/suite.yaml`. Cursor command: `/sql-pro`.
