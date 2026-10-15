# Swarm SDK optimization: observability, token accuracy, RAM, and Radeon 5300M acceleration

- Status: draft, pending user review
- Date: 2026-09-29
- Scope: `src/swarm_sdk/{observability,prompting,retrieval,core,gpu,memory,models,config}`, `Agents/benchmark/`, `Agents/{MLSpecialist,Optimizer,DevOps}/AGENTS.md`, `Main/config/swarm.yaml`

## Goal

Improve the LangGraph Swarm SDK along six axes the user named: precision/accuracy, token usage, observability, import hygiene, RAM usage, and free-threading — plus, once scoped, explicit use of the host's AMD Radeon Pro 5300M via OpenCL for INT8 inference-adjacent math, semantic cache, and vector DB search. Benchmark and agent-contract updates track the new capabilities.

## Why now

No incident drove this — it's a proactive efficiency pass. The `observability` extra is declared in `pyproject.toml` but wired nowhere. `SemanticCache.lookup()` loads every cached vector into RAM on every call (confirmed by reading `retrieval/cache.py:61`). Token counts reported in `RunResult` are text-length estimates, not the LLM's actual `usage_metadata`. The Radeon 5300M is already probed by `gpu/report.py` but under-used: only float32 dot/cosine/top-k run on it today.

## Non-goals

- No new runtime dependencies beyond what `pyproject.toml` already declares as optional extras (`observability`, `opencl`).
- No changes to `execution/concurrency.py`'s cap constants (8 / 32) — those are already correct for this host.
- No changes to `serving/`, `pb/`, or any agent role beyond the three named (MLSpecialist, Optimizer, DevOps).
- No TaskGroup/asyncio.gather migration (deferred — this is Option B, not Option C from the original brainstorm).

## Design

### 1. Observability layer (`observability/metrics.py`, `observability/tracing.py`)

New files, both no-ops when their optional dependency is absent so the SDK works with only core deps installed:

**`metrics.py`** — module-level Prometheus instruments (`prometheus-client`, added to the `observability` extra):

```python
swarm_requests_total        Counter(labels: mode, cached)
swarm_token_usage_total     Counter(labels: agent, model)
swarm_cache_hits_total      Counter(labels: kind)      # exact | semantic
swarm_step_latency_seconds  Histogram(labels: step)    # route | recall | swarm | cache_lookup
swarm_active_threads        Gauge()
```

Each call site wraps its increment in `try/except ImportError` at import time (module-level `_ENABLED` flag), not per-call, so the hot path has no branch cost when disabled.

**`tracing.py`** — thin OTel wrapper:

```python
@contextmanager
def span(name: str, **attrs: object) -> Iterator[None]: ...
```

No-op context manager when `opentelemetry-api` isn't installed or no `TracerProvider` is configured. Used in `core/swarm.py`:

```python
async with tracing.span("swarm.run", mode=route.mode):
    ...
```

**`observability/usage.py`** — `UsageLog.add()` gains keyword args `latency_ms: float = 0.0` and `model: str = ""` (backwards-compatible). `summary()` adds `latency_ms_total` and `cost_estimate_usd` (a small constant `dict[str, tuple[float, float]]` mapping model name → `(input_$/1k, output_$/1k)`; unknown models score `0.0`, never raise).

### 2. Token accuracy (`models/chat.py`, `prompting/budget.py`)

`complete()` return type changes from `str` to `tuple[str, int]` (text, total_tokens). Extraction:

```python
usage = getattr(response, "usage_metadata", None)
tokens = usage["total_tokens"] if usage else count_text(text)  # fallback estimate
```

Callers updated: `FallbackChain.complete()`, `core/swarm.py::_route()`, `core/swarm.py::_swarm()`. `RunResult.tokens` now reflects real provider usage when available, falling back to the existing text-length estimate only when a provider omits `usage_metadata`.

**Token count LRU cache** in `prompting/budget.py`:

```python
_COUNT_CACHE: dict[tuple[int, int], int] = {}   # (hash(text), id(tokenizer) or 0) -> count
_COUNT_CACHE_MAX = 512
```

`count_text()` checks the cache first. Eviction: when `len > _COUNT_CACHE_MAX`, drop the oldest half (insertion order, plain dict — no `OrderedDict` needed since Python 3.7+ dicts preserve insertion order). No new dependency.

### 3. RAM: SemanticCache → OpenClVecStore-backed index

`retrieval/cache.py`: `SemanticCache` gains an in-memory `OpenClVecStore` (or NumPy fallback if OpenCL unavailable) as its semantic index, replacing the `fetchall()` linear scan:

- **Init**: load up to 256 most-recent rows from the `semantic_cache` SQLite table into the vector store (warm-up).
- **`lookup()`**: exact-hash check in SQLite first (unchanged), then one `_vec_store.search(query_vec, k=1)` call instead of loading all vectors.
- **`store()`**: persist to SQLite (unchanged) + `_vec_store.add(text, vector)`.
- Falls back to the pre-existing linear-scan path when `settings.opencl_enabled=False` and store isn't backed by OpenCL — behavior-preserving for hosts without OpenCL.

`SqliteVecStore` and `SemanticCache` both add `PRAGMA journal_mode=WAL` immediately after connecting — concurrent reads no longer block on writes. One line each, no schema change.

`core/swarm.py`: `SwarmSDK.__init__` gains `max_threads: int = 200`. In `run()`, before adding a new `thread_id`, if `len(self._threads) >= max_threads`, evict the oldest `max_threads // 4` thread IDs from `self._threads` (plain set, so track insertion via a companion `collections.deque` for order) and delete their state from the `InMemorySaver` checkpointer via its public `delete_thread` API if present, else skip (best-effort — no crash if the checkpointer doesn't expose it).

### 4. Import hygiene (`core/swarm.py`, `observability/usage.py`)

- `core/swarm.py`: `FastEmbedder`, `LlamaCppEmbedder` imports move from module top-level into `default_embedder()` (already partially lazy for `qdrant`/`faiss`/`mem0`/`opencl` stores in `open_store()` — this extends the same pattern to embedders).
- `observability/usage.py`: `import polars as pl` moves inside `UsageLog.summary()` — the constructor and `add()` no longer force-load Polars; only summarizing does.

### 5. Radeon 5300M OpenCL acceleration (`gpu/`, `memory/opencl_store.py`)

**New kernels in `gpu/opencl_math.py`** (added to `_SOURCE`):

```c
// fused normalize + dot in one pass — avoids materializing normalized matrix
__kernel void normalize_dot(float* matrix, float* query, float* out, uint rows, uint cols);

// float32 row -> int8 + per-row symmetric scale (scale = max(|v|)/127)
__kernel void quantize_int8(float* matrix, char* out_int8, float* out_scale, uint rows, uint cols);

// fused dequantize int8 rows + dot with float32 query
__kernel void dequant_dot(char* int8_mat, float* scales, float* query, float* out, uint rows, uint cols);

// 1-bit sign quantization: bit=1 if v>=0 else 0, packed into uint32 words
__kernel void binary_quantize(float* matrix, uint* out_bits, uint rows, uint cols);

// Hamming distance for binary vectors (popcount of XOR); LOWER out[r] = more similar.
// Python wrapper inverts sign (out = total_bits - distance) so callers can top-k
// with the same "higher is better" convention as the other similarity kernels.
__kernel void binary_dot(uint* bits_mat, uint* query_bits, uint* out, uint rows, uint words);

// batch softmax for reranker scores
__kernel void batch_softmax(float* scores, float* out, uint n);
```

**New Python exports from `gpu/__init__.py`:**

```python
normalize_dot(matrix, query) -> np.ndarray
quantize_int8(matrix) -> tuple[np.ndarray, np.ndarray]      # (int8_matrix, scales)
dequant_dot(int8_mat, scales, query) -> np.ndarray
binary_quantize(matrix) -> np.ndarray                        # packed uint32 words
binary_dot(bits_mat, query_bits) -> np.ndarray                # higher = more similar (inverted Hamming distance)
batch_softmax(scores) -> np.ndarray
```

Every export follows the existing dispatcher pattern in `opencl_math.py`: try OpenCL, catch and log, fall back to NumPy — callers never branch on availability.

**`memory/opencl_store.py`**: `quantize: Literal["none", "int8", "binary"] = "none"` replaces a hypothetical boolean (this is a new kwarg, not a rename — no existing callers break since the default preserves current float32 behavior). Search path picks the matching kernel (`topk_ip` for `none`, `dequant_dot` for `int8`, `binary_dot` for `binary`).

**`retrieval/rerank.py`**: `FastEmbedReranker` uses `gpu.batch_softmax` instead of `np.exp`-based normalization when scoring more than a threshold (e.g. 32) candidates — small batches stay on CPU since kernel dispatch overhead would dominate.

**Router structured output (`models/chat.py`, `core/swarm.py`)**: `_route()` first attempts provider structured output — `model.bind(response_format={"type": "json_object"})` when the model supports it (LangChain exposes this uniformly via `with_structured_output` for models that support it; check via `hasattr`) — falling back to the existing regex `_JSON_OBJECT` extraction for providers/models that don't. Controlled by `Settings.router_structured_output: bool = True`.

**Prompt-cache-friendly packing (`prompting/budget.py`)**: `PackedPrompt` gains two read-only properties, `prefix` (the stable `system` text) and `suffix` (the variable `user` text) — these already exist as separate fields (`system`, `user`); the change is exposing them under names callers can pass directly to providers that split cache-eligible vs variable segments (e.g. Anthropic's `cache_control` blocks). No data model change, just call-site plumbing in `core/swarm.py::_route()`/`_swarm()` to pass `system=` and `user=` separately to `complete()` instead of pre-joining via `.text`.

**`config/settings.py`** new fields (all opt-in, default preserves current behavior):

```python
opencl_quantize: Literal["none", "int8", "binary"] = "none"
semantic_cache_on_gpu: bool = False
cache_ttl_days: int | None = None
router_structured_output: bool = True
```

**`Main/config/swarm.yaml`**: new `opencl:` block mirroring the pattern already used in `Main/config/swarm-bge-m3-radeon.yaml`:

```yaml
opencl:
  enabled: true
  quantize: int8
  semantic_cache_on_gpu: true
```

### 6. Benchmarks

New task folders under `Agents/benchmark/Tasks/` (each follows the existing `Tasks/{name}/` + scripted-model pattern — no API keys):

- **`gpu_quantization/`** — sweeps `none`/`int8`/`binary` on `OpenClVecStore`: resident RSS, p50/p95 search latency, Recall@K vs exact NumPy float32. Extends the `gpu_retrieval` task's methodology rather than duplicating its harness.
- **`semantic_cache_gpu/`** — compares old (SQLite `fetchall` linear scan) vs new (`OpenClVecStore`-backed) `SemanticCache.lookup()` latency and RSS at 1k / 10k / 100k cached entries.
- **`structured_router/`** — JSON parse failure rate: regex extraction vs structured output, over a fixed set of scripted adversarial model outputs (malformed JSON, prose-wrapped JSON, truncated JSON).
- **`token_count_cache/`** — measures `encode()` call reduction from the LRU token-count cache across a multi-turn session replay (extends `token_cache_hit`'s methodology to counting, not just response caching).

`Agents/benchmark/README.md` gets one new section, "GPU quantization & structured routing," documenting each command, following the file's existing doc style (command block + one-paragraph description of what's measured).

### 7. Agent contract updates

No new agents, no `coordination.yaml` structural change — three existing contracts gain a documented responsibility each:

- **`Agents/MLSpecialist/AGENTS.md`**: owns choosing `opencl_quantize` (`none`/`int8`/`binary`) based on `gpu.report.acceleration_report()` output, and embedder backend tradeoffs.
- **`Agents/Optimizer/AGENTS.md`**: owns semantic-cache threshold calibration and (future) adaptive think-level tuning, reading `UsageLog`/Prometheus latency data — consistent with its existing "profile before optimizing" norm.
- **`Agents/DevOps/AGENTS.md`**: owns OTel/Prometheus exporter wiring and the `swarm.yaml` `opencl`/`observability` config blocks.

## Testing

- `Agents/tests/`: new/updated unit tests for `count_text()` LRU cache correctness (hit/miss/eviction), `SemanticCache` GPU-backed lookup parity with the old linear scan (same top-1 result on a fixed corpus), `quantize_int8`/`dequant_dot`/`binary_quantize`/`binary_dot` numerical correctness against NumPy reference implementations (tolerance appropriate to each quantization's precision loss), `UsageLog.add()` new kwargs default correctly, WAL mode doesn't break existing SQLite tests.
- Full quality gate per `AGENTS.md`: `pytest`, `ruff check`, `ty check`, `python -m swarm_sdk.agents.validate`.
- New benchmark tasks run once manually to confirm they execute and produce a report; not part of the default CI gate (matches existing `Agents/benchmark/` convention — `results/` is gitignored, benchmarks are informational, not pass/fail).

## Rollout

All new behavior is either additive-with-safe-defaults (`opencl_quantize="none"`, `semantic_cache_on_gpu=False`, `router_structured_output=True` — but falls back to today's regex path automatically) or purely internal (token LRU cache, import laziness, WAL mode). No migration needed. Existing `swarm.yaml` files without an `opencl:` block continue to work — `Settings` field defaults cover it.
