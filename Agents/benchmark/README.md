# Benchmarks

Task folders under `Tasks/{name}/` measure token usage, cache hits, retrieval quality, and swarm behavior using **predefined models** from [Main/config/swarm.yaml](../../Main/config/swarm.yaml) and scripted chat models (no API keys in CI).

## Token-minimization pipeline (what we score)

1. Exact + semantic cache before any LLM call.
2. Router on `think_level: low` and cheapest route in `model_select.routes`.
3. Hybrid dense + BM25 recall, dedupe, rerank, inject only top-k snippets.
4. Tokenizer budget + think-level caps before prompts.
5. Parallel fan-out with JSON briefs instead of full transcripts.

## Run

```bash
uv run pytest Agents/benchmark -q
uv run python -m benchmark.run --task token_cache_hit
```

Results (optional): `Agents/benchmark/results/{task}/` (gitignored).

## Embedding throughput (CPU vs CoreML GPU)

Compare ONNX Runtime providers for FastEmbed (requires `uv sync --extra jupyter`):

```bash
uv run python benchmark/CPU_GPU.py
uv run python benchmark/CPU_GPU.py --write-results --json
uv run python benchmark/CPU_GPU.py --cuda   # include CUDA when available
```

## Bounded vector retrieval (OpenCL or NumPy fallback)

The vector search benchmark sweeps chunk sizes and reports p50/p95 latency,
process CPU time, peak RSS, resident vector bytes, and Recall@K against exact
NumPy inner product. It prints the selected chunk size; `--write-results`
stores the report under the gitignored `Agents/benchmark/results/` directory. It does
not change runtime settings automatically.

```bash
uv run python Agents/benchmark/Tasks/gpu_retrieval/benchmark_gpu_retrieval.py
uv run python Agents/benchmark/Tasks/gpu_retrieval/benchmark_gpu_retrieval.py --write-results
```

For the Radeon, enable the optional dependency and select the discrete GPU
before Python imports the OpenCL dispatcher:

```bash
SWARM_OPENCL_DEVICE="AMD Radeon Pro 5300M" uv run --extra opencl \
  python Agents/benchmark/Tasks/gpu_retrieval/benchmark_gpu_retrieval.py --write-results
```

The BGE-M3 + SQLite INT8 runtime profile is
[`config/swarm-bge-m3-radeon.yaml`](../../Main/config/swarm-bge-m3-radeon.yaml). Activate
it with `SWARM_CONFIG_PATH=config/swarm-bge-m3-radeon.yaml` and install the
`molten` extra. It creates a separate 1024-dimension database under
`Essentials/llama/`, preserving existing 384-dimension memory data.

Use a small workload for a quick smoke measurement with `--rows 512 --dim 384
--queries 10`. The report includes the actual OpenCL availability/device state;
when OpenCL is missing or unusable, the same workload measures the NumPy path.
Runtime offload defaults to at least 8192 rows because this machine's measured
OpenCL path was slower through 4096×1024 vectors. The benchmark forces OpenCL
on for comparison, then reports the fastest measured backend and chunk size.

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
