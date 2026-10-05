# Benchmarks

One QA tree: benchmark **task folders** under `Tasks/{name}/` measure token usage, cache hits, retrieval quality, and swarm behavior using **predefined models** from [Main/config/swarm.yaml](../../Main/config/swarm.yaml) and scripted chat models (no API keys in CI); **unit and integration tests** for the SDK live in [`tests/`](tests/) (importable as `benchmark.tests.*`, shared fakes in `tests/fakes.py`).

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

### Redis and local response-cache latency (`Tasks/redis_cache/`)

Compare SQLite exact hits with Redis exact hits, Redis misses that fall back to
SQLite exact hits, and semantic misses with or without the Redis lookup. Each
path runs at 100, 1,000, and 10,000 entries using paired ABBA batches (50
rounds, 500 operations per sample by default). Reports include raw samples,
p50/p95/p99, MAD, coefficient of variation, paired deltas, and a seeded 95%
bootstrap interval. A single process run is never labeled a speedup.

CI starts an ephemeral Redis 7 service and uploads the JSON report as the
`redis-cache-benchmark-*` artifact. Run locally with a real Redis service and
the optional client dependency:

```bash
uv sync --extra redis
REDIS_URL=redis://localhost:6379/0 PYTHONPATH=Agents:. uv run python Agents/benchmark/Tasks/redis_cache/benchmark_redis_cache.py --write-results
uv run pytest Agents/benchmark/Tasks/redis_cache -q
```

Tests use an explicitly enabled in-memory stand-in; the benchmark CLI refuses
to silently treat that stand-in as real Redis. Results do not impose
machine-dependent CI latency thresholds.

### Persistent cache storage and resource use (`Tasks/cache_storage/`)

Compare SQLite with DuckDB when the optional `duckdb` package is installed.
Each engine and cache size runs in a fresh subprocess so peak RSS is not
contaminated by a previous engine. The harness reports exact point hits and
misses, a bounded 256-row semantic candidate scan, insert cost, process CPU,
peak RSS, and database size. It isolates storage operations; embedding and
Redis network time are intentionally excluded.

```bash
PYTHONPATH=Agents:. uv run python Agents/benchmark/Tasks/cache_storage/benchmark_cache_storage.py
uv run pytest Agents/benchmark/Tasks/cache_storage -q
```

SQLite runs with the standard library. To include DuckDB, install it in the
benchmark environment explicitly; it is not a core SDK dependency.

## Embedding throughput (CPU vs CoreML GPU)

Compare ONNX Runtime providers for FastEmbed (requires `uv sync --extra jupyter`):

```bash
uv run python Agents/benchmark/CPU_GPU.py
uv run python Agents/benchmark/CPU_GPU.py --write-results --json
uv run python Agents/benchmark/CPU_GPU.py --cuda   # include CUDA when available
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
[`Main/config/swarm-bge-m3-radeon.yaml`](../../Main/config/swarm-bge-m3-radeon.yaml). Activate
it with `SWARM_CONFIG_PATH=Main/config/swarm-bge-m3-radeon.yaml` and install the
`molten` extra. It creates a separate 1024-dimension database under
`Main/Essentials/llama/`, preserving existing 384-dimension memory data.

The profile was smoke-checked on 2026-09-29 with the local BGE-M3 Q8_0 GGUF.
llama.cpp offloaded all 25/25 layers to the Radeon Pro 5300M through Vulkan;
embeddings returned to Python as float32 and SQLite stored each 1024-D vector
as an INT8 payload (1024 bytes). BGE-M3 does not need `query:` / `passage:`
prefixes, so the embedding wrapper leaves its text unmodified. The local SQLite
build has sqlite-vec but no FTS5; keyword lookup now falls back to a small Python
token matcher. The native sqlite-vec search path runs inside SQLite and does not
use OpenCL. OpenCL selection is independent and only accelerates the GPU math
paths that explicitly call its dispatcher. The 16-document improvised-data smoke
is functional coverage, not a retrieval-quality benchmark; results and the
llama.cpp offload log are in
[`results/int8_gpu_vectorized/`](results/int8_gpu_vectorized/) (gitignored).

Use a small workload for a quick smoke measurement with `--rows 512 --dim 384
--queries 10`. The report includes the actual OpenCL availability/device state;
when OpenCL is missing or unusable, the same workload measures the NumPy path.
Runtime offload defaults to at least 8192 rows because this machine's measured
OpenCL path was slower through 4096×1024 vectors. The benchmark forces OpenCL
on for comparison, then reports the fastest measured backend and chunk size.

### Efficiency gains vs replaced behavior (`Tasks/efficiency_gains/`)

```bash
PYTHONPATH=Agents:. uv run python -m benchmark.Tasks.efficiency_gains.benchmark_efficiency_gains --write-results
uv run --extra dev pytest Agents/benchmark/Tasks/efficiency_gains -q
```

Each scenario re-implements the replaced (pre-optimization) behavior inline and
runs the current SDK on the identical deterministic workload; improvements are
measured, never hardcoded. Measured 2026-09-30 (seed 7, 200 answers / 48 texts /
400 docs, `results/efficiency_gains/latest.json`):

| Metric                                   | Baseline | Current | Improvement        |
| ---------------------------------------- | -------: | ------: | -----------------: |
| Fan-out brief tokens into synthesizer    |   13,200 |  11,386 | **−13.75%**        |
| BGE-M3 embedding input tokens            |      480 |     336 | **−30.0%**         |
| Plan recovery after rejected first reply |       0% |    100% | **+100 pp**        |
| Bogus empty answers served from cache    |     100% |      0% | **−100%**          |
| Recall prompt tokens (50% dup memories)  |      239 |     119 | **−50.2%**         |
| Keyword search on FTS5-less SQLite       |    crash | working | **+100 pp**, recall 1.0, p50 0.73 ms |

Mean measured improvement across the token metrics: **48.5% fewer tokens**; the
two 0→100 metrics (delegation recovery, cache integrity) are percentage-point
wins rather than ratios.

### Cold import vs eager-import stack (`Tasks/cold_import/`)

```bash
PYTHONPATH=Agents uv run python -m benchmark.Tasks.cold_import.benchmark_cold_import
uv run --extra dev pytest Agents/benchmark/Tasks/cold_import -q
```

Fresh-subprocess medians: `import swarm_sdk` today versus the same import plus
the eager `langchain`/`langgraph`/`langgraph_swarm`/`tokenizers` stack the lazy
imports replaced. Measured 2026-10-01 (3 runs, `results/`):

| Metric            | Baseline    | Current    | Improvement   |
| ----------------- | ----------: | ---------: | ------------: |
| Cold import wall  | 1,636.30 ms | 672.02 ms  | **−58.93%**   |

### Fail-fast wave abort vs `asyncio.gather` (`Tasks/wave_fail_fast/`)

```bash
PYTHONPATH=Agents uv run python -m benchmark.Tasks.wave_fail_fast.benchmark_wave_fail_fast
uv run --extra dev pytest Agents/benchmark/Tasks/wave_fail_fast -q
```

The baseline runs the replaced `bounded_gather` body inline: one failing step
(5 ms) in a 6-step wave (50 ms each, cap 3) and its siblings keep running to
completion. Current SDK cancels them via `TaskGroup`. Measured 2026-10-01
(5 runs): tokens burned **300 → 0 (−100%)**, sibling tasks still running after
the failure **5 → 0 (−100 pp)**.

### Real Radeon run (2026-09-29)

On the Intel MacBook Pro, OpenCL enumerated and executed on `AMD Radeon Pro 5300M
Compute Engine`. The real kernel result for an 8192×384 dot workload matched NumPy
with maximum absolute error `5.34e-05`. With deterministic normalized synthetic
vectors (seed 7), recall@10 was 1.0 for every CPU and OpenCL profile. OpenCL was
slower in both recorded retrieval workloads: at 2048×384 best p95 was 4.13 ms
versus NumPy 0.21 ms; at 8192×1024 best p95 was 83.19 ms versus NumPy 1.92 ms.
The best measured backend was NumPy. Run artifacts and compressed input data are
under [`results/gpu_retrieval/runs/20260929T192753Z/`](results/gpu_retrieval/runs/20260929T192753Z/)
(gitignored). The 7 GPU math tests passed with AMD explicitly selected and
`SWARM_OPENCL_MIN_ROWS=1` so the small test matrices actually use the GPU.

## Model Delegation benchmark suite

Provider-routing and GPU-dispatch cases under `Tasks/model_delegation/`. No API keys required.

```bash
uv run pytest Agents/benchmark/Tasks/model_delegation -q
uv run python -m benchmark.run --task model_delegation
```

Case definitions: `benchmark/model_delegation/suite.yaml`.

## Model effort and task scores

`Tasks/model_effort/task.yaml` defines six small classification, extraction, and
arithmetic cases. The suite records exact-answer score, provider-reported input
and output tokens, total wall time, model-call time, and local overhead (wall
minus model-call time). Summary rows group by task type, registry model, and
configured effort; their `average_overhead_ms` excludes provider wait. Missing
provider usage stays `null`, never a guessed token count. Scripted mode checks
the harness and reports reference answers; its scores do not measure model quality.

```bash
PYTHONPATH=Agents uv run python -m benchmark.model_effort --write-results
PYTHONPATH=Agents uv run python -m benchmark.model_effort --live --model openai:gpt-4o-mini --write-results
PYTHONPATH=Agents uv run python -m benchmark.model_effort --codex-profile PROFILE --model openai:gpt-6-luna --write-results
PYTHONPATH=Agents uv run python -m benchmark.model_effort --auto --write-results
uv run pytest Agents/benchmark/Tasks/model_effort -q
```

Live mode uses the model and effort assigned in the registry. Effort is a route
label; the benchmark does not send a reasoning-effort parameter to providers
whose API may not support it. Live mode requires a selected model and resolves
its named credential from the macOS Keychain via `swarm_sdk.vault`. Set it with
`uv run swarm-vault set OPENAI_API_KEY` (or the selected route's `api_key_env`).
The report contains no prompts, replies, or credentials. Results written with
`--write-results` go to the gitignored `results/model_effort/latest.json`.
Use `--json` to print the full per-case report instead of the grouped table.
`--auto` selects one low-effort registry API model whose named credential is
available in the environment or Keychain; if none is available, it uses the
`Comand` Codex profile configured in `task.yaml` when installed. It runs the
fixed cases in round-robin task-type order and stops before a projected token
budget breach (default 50,000 reported tokens). The cap uses prior usage and
can be exceeded by a single unexpectedly large call. The report marks partial
runs with `complete: false` and `stopped_reason`; change the cap with
`--max-total-tokens`. Provider errors also stop the run with only the exception
type in the report, avoiding credential-bearing exception text. The mode makes
real calls only when `--auto` is explicit.
The Codex mode calls `codex exec -p PROFILE` as the benchmark agent with the
registry model and effort. It runs read-only in a temporary directory and reads
Codex CLI usage events. The profile must already exist under `CODEX_HOME`; CLI
authentication is managed by Codex rather than an API key in source code.

On 2026-10-03, `Comand` with `openai:gpt-6-luna` at medium effort scored 6/6
on this small suite. Codex reported 82,055 tokens across those calls and the
CLI invocation intervals totaled 24.7 seconds; mean local overhead was 0.011 ms.
These token counts include the Codex agent context, so this route is costly for
single-answer tasks despite its perfect score here. The detailed local report
is `results/model_effort/codex_full_2026-10-03.json` (gitignored). The subsequent
`--auto` run selected that route without a manual profile flag, covered all
three task types in three cases, and stopped before the next projected call at
41,028 reported tokens. Its 3/3 score and `projected_token_budget` stop are in
`results/model_effort/latest.json` (gitignored).

## SQL Pro benchmarkable suite

Skill-aligned SQLite cases under `sql_pro/` (correctness, join rewrites, index plans). No LLM required.

Both `pytest Agents/benchmark/Tasks/sql_pro` and `python -m benchmark.run --task sql_pro` execute the full suite (the task module delegates to `benchmark.sql_pro.run`).

```bash
uv run python -m benchmark.sql_pro.run
uv run python -m benchmark.sql_pro.run --write-results
uv run pytest Agents/benchmark/Tasks/sql_pro -q
uv run python -m benchmark.run --task sql_pro
```

Case definitions: `benchmark/sql_pro/suite.yaml`. Cursor command: `/sql-pro`.

## Code-agent harness calibration (20 tasks)

This offline suite feeds each case's reference solution to the scorer as a
scripted Coder. It checks the scorer and acceptance tests and gives an upper
bound; it does **not** measure the current Coder agent or compare models. The
reported token, latency, and change metrics describe the reference harness.

```bash
uv run pytest Agents/benchmark/Tasks/codeagent_bencheval -q
uv run python -m benchmark.run --task codeagent_bencheval
```

Case definitions: `benchmark/Tasks/codeagent_bencheval/cases.py`. To measure a
real agent, connect a Coder implementation instead of `_reference_agent`.

## WebSearch tools (one query, one row per tool)

Sends a single query to every WebSearch searcher, scrapes each tool's hits, and reports per tool:
sites appeared, sites scraped, normalization % (`1 - normalized_chars/raw_html_chars`), tokens
(`cl100k_base` count of the normalized text), API-reported tokens (Google grounding), and
search/scrape time. Tools without their env key report zeros. Offline check:
`uv run --extra dev pytest Agents/benchmark/Tasks/websearch_tools -q`.

```bash
PYTHONPATH=Agents:. uv run python -m benchmark.websearch_bench --query "(a|b) AND (c) after:2026-03-01" --write-results
```
