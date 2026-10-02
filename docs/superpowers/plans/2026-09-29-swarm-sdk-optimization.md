# Swarm SDK Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut token/RAM cost and add observability to the Swarm SDK, and put the Radeon Pro 5300M (OpenCL) to work on INT8/binary vector math, the semantic cache and reranking.

**Architecture:** Additive changes behind safe defaults. New leaf modules (`observability/metrics.py`, `observability/tracing.py`) are no-ops without their optional deps. New OpenCL kernels follow the existing `try GPU, fall back to NumPy` dispatcher in `gpu/opencl_math.py`. `SemanticCache` swaps its `fetchall()` linear scan for an in-memory `OpenClVecStore` index. Benchmarks and three agent contracts document and measure the result.

**Tech Stack:** Python >=3.14.5, uv, pytest + hypothesis, ruff, ty, NumPy, pyopencl (optional), prometheus-client and OpenTelemetry (optional, `observability` extra), LangChain/LangGraph.

**Spec:** `docs/superpowers/specs/2026-09-29-swarm-sdk-optimization-design.md`

## Global Constraints

- Python `>=3.14.5`, managed with uv; run everything as `uv run --extra dev ...`.
- Every new module starts with a docstring, then `from __future__ import annotations` (project rule).
- Ruff `line-length = 100`, `target-version = "py314"`, rules `E,F,I,UP`. No new `# noqa`/`# type: ignore`/skip/xfail without a named rule and reason.
- No new runtime dependencies. `prometheus-client` is added to the `observability` optional extra only.
- Do not change `execution/concurrency.py` caps (8 GIL / 32 free-threaded), `serving/`, `pb/`, or any agent contract other than `MLSpecialist`, `Optimizer`, `DevOps`.
- All new behavior defaults to today's behavior: `opencl_quantize="none"`, `semantic_cache_on_gpu=False`, `cache_ttl_days=None`; `router_structured_output=True` must auto-fall-back to the regex path.
- The real config file is `src/swarm_sdk/agents/config/swarm.yaml`; `Main/config/swarm.yaml` is a symlink to it. Edit the real file.
- Quality gate (run once at the end, and per-task where noted):
  ```bash
  uv run --extra dev pytest Agents/tests Agents/benchmark -q --tb=short
  uv run --extra dev ruff check src Agents/tests Agents/benchmark Main
  uv run --extra dev ty check src Agents/tests Agents/benchmark Main
  uv run python -m swarm_sdk.agents.validate
  ```
- Commits: branch `2026-09-28-6u8s` (not protected). Stage files by name only. The working tree has unrelated pre-existing modifications (`README.md`, `Agents/benchmark/README.md`, `Agents/tests/test_llama_embedder.py`, `Agents/tests/test_memory.py`, `Main/config/swarm-bge-m3-radeon.yaml`, `src/swarm_sdk/memory/sqlite_vec.py`, `src/swarm_sdk/retrieval/embeddings.py`). Never `git add -A`. Where a task edits one of those files, run `git diff <file>` first and stage it whole only after confirming with the user, or use `git add -p` for just your hunks.
- Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Deviations from the spec (found while reading the code)

1. **`complete()` keeps returning `str`.** The spec says it returns `tuple[str, int]`. Five callers use it (`orchestrator/spawn.py:127`, `orchestrator/worker.py:223`, `execution/fanout.py:71,82`, `models/selection.py:129`, `core/swarm.py:291`), two of them outside the spec's scope. Instead a new `complete_with_usage()` returns `(text, tokens)` and `complete()` delegates to it. Same outcome, no blast radius.
2. **Embedder imports are already lazy.** `FastEmbedder`/`LlamaCppEmbedder` are plain classes; their packages load through `importlib` inside the class. Moving the class imports would save nothing. Task 2 therefore only lazy-loads `polars` (the one real eager heavy import) and adds a guard test.
3. **Config lives under `vectorstore:` / `router:`**, not a new `opencl:` block, because `vectorstore.opencl_enabled` already exists. `semantic_cache_on_gpu` and `cache_ttl_days` are `Settings`-only, like the existing `cache_path` and `semantic_threshold`.
4. **TTL scope.** The spec only names `cache_ttl_days`. It gets a real implementation for `SemanticCache` (Task 7). `SqliteVecStore` TTL is out of scope: its tables have no timestamp column.
5. **Fewer GPU kernels than the spec lists.** `quantize_int8`, `binary_quantize` and `batch_softmax` are NumPy-only: they run once per insert or over ~20 scores, below the 8192-row GPU threshold in `_gpu_threshold()`, so a kernel would be dead code. GPU kernels: `normalize_dot`, `dequant_dot`, `binary_dot`. Task 19 measures the crossover; add kernels only if it justifies them.
6. **Out of scope, observed:** `gpu/opencl_math.py` runs `_STATE = _ClState()` at import time, which imports `pyopencl` and compiles the program on `import swarm_sdk`. Making that lazy touches `reset_opencl()` and every `_STATE` user; propose it as a follow-up.

## Review Focus

Failure modes the spec implies but no obvious task test covers; each has a test in the owning task.

1. Same text counted with two different tokenizers must not share a cache entry (Task 1).
2. Token-count cache under concurrent threads (free-threaded build) must not raise or exceed its bound (Task 1).
3. Provider omits `usage_metadata`, or returns it with `total_tokens` missing: fall back to the estimate, never raise (Task 13).
4. Router model returns prose-wrapped, truncated, or empty JSON: `RouteDecision()` default, never an exception (Task 14).
5. `SemanticCache` with zero rows, a wrong-dimension stored blob, or a persisted DB written by the old code (no `inserted_at` column) must still work (Tasks 7, 12).
6. `binary_dot` / `dequant_dot` on an all-zero vector, one-row matrix, and `dim` not a multiple of 32 (Tasks 8, 9).
7. `OpenClVecStore(quantize="binary")` ring-buffer wraparound keeps ids and texts aligned (Task 11).
8. Thread eviction while a run for the evicted `thread_id` is in flight must not crash (Task 17).

---

### Task 1: Token-count LRU cache

**Files:**
- Modify: `src/swarm_sdk/prompting/budget.py` (module constants near line 15; `count_text` at line ~85)
- Test: `Agents/tests/test_tokens.py`

**Interfaces:**
- Produces: `budget._COUNT_CACHE: dict[tuple[int, int], int]`, `budget._COUNT_CACHE_MAX = 512`, `budget._COUNT_LOCK`. `count_text(text, tokenizer=None) -> int` keeps its signature.

- [ ] **Step 1: Write the failing tests** (append to `Agents/tests/test_tokens.py`)

```python
import threading

from swarm_sdk.prompting import budget


class _CountingTok:
    def __init__(self, per_char: int = 1) -> None:
        self.calls = 0
        self.per_char = per_char

    def encode(self, text: str) -> list[int]:
        self.calls += 1
        return [0] * (len(text) * self.per_char)


def test_count_text_cache_avoids_reencode() -> None:
    budget._COUNT_CACHE.clear()
    tok = _CountingTok()
    assert count_text("hello world", tok) == 11
    assert count_text("hello world", tok) == 11
    assert tok.calls == 1


def test_count_text_cache_is_per_tokenizer() -> None:
    budget._COUNT_CACHE.clear()
    one, two = _CountingTok(1), _CountingTok(2)
    assert count_text("abc", one) == 3
    assert count_text("abc", two) == 6


def test_count_text_cache_is_bounded() -> None:
    budget._COUNT_CACHE.clear()
    tok = _CountingTok()
    for i in range(budget._COUNT_CACHE_MAX + 100):
        count_text(f"t{i} x", tok)
    assert len(budget._COUNT_CACHE) <= budget._COUNT_CACHE_MAX


def test_count_text_cache_threadsafe() -> None:
    budget._COUNT_CACHE.clear()
    tok = _CountingTok()
    errors: list[BaseException] = []

    def work(offset: int) -> None:
        try:
            for i in range(300):
                count_text(f"w{offset}-{i}", tok)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(budget._COUNT_CACHE) <= budget._COUNT_CACHE_MAX
```
- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest Agents/tests/test_tokens.py -q --tb=short -k count_text_cache`
Expected: FAIL with `AttributeError: module 'swarm_sdk.prompting.budget' has no attribute '_COUNT_CACHE'`.

- [ ] **Step 3: Implement**

In `budget.py` add `import threading` to the stdlib imports, then after `_ENCODING_MISSING`:

```python
_COUNT_CACHE: dict[tuple[int, int], int] = {}
_COUNT_CACHE_MAX = 512
_COUNT_LOCK = threading.Lock()
```

Replace `count_text` body (keep docstring):

```python
    if not text:
        return 0
    key = (hash(text), id(tokenizer) if tokenizer is not None else 0)
    cached = _COUNT_CACHE.get(key)
    if cached is not None:
        return cached
    if tokenizer is not None:
        count = _count_with(tokenizer, text)
    else:
        encoding = _tiktoken_encoding()
        if encoding is not None:
            count = _count_with(encoding, text)
        else:
            count = len(_WHITESPACE.pre_tokenize_str(text))
    with _COUNT_LOCK:
        if len(_COUNT_CACHE) >= _COUNT_CACHE_MAX:
            for stale in list(_COUNT_CACHE)[: _COUNT_CACHE_MAX // 2]:
                del _COUNT_CACHE[stale]
        _COUNT_CACHE[key] = count
    return count
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run --extra dev pytest Agents/tests/test_tokens.py -q --tb=short`
Expected: all PASS (existing hypothesis tests included).

- [ ] **Step 5: Lint and commit**

```bash
uv run --extra dev ruff check src/swarm_sdk/prompting/budget.py Agents/tests/test_tokens.py
git add src/swarm_sdk/prompting/budget.py Agents/tests/test_tokens.py
git commit -m "perf: cache token counts (bounded, thread-safe)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Lazy `polars` import + import-guard test

**Files:**
- Modify: `src/swarm_sdk/observability/usage.py`
- Create: `Agents/tests/test_import_laziness.py`

**Interfaces:**
- Produces: `UsageLog` unchanged publicly; `import swarm_sdk` no longer loads `polars`.

- [ ] **Step 1: Write the failing test**

```python
"""Heavy optional packages must not load on ``import swarm_sdk``."""

from __future__ import annotations

import subprocess
import sys


def _loaded_after_import(*names: str) -> set[str]:
    code = (
        "import sys, swarm_sdk; "
        f"print(','.join(n for n in {names!r} if n in sys.modules))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=180,
        check=True,
    ).stdout.strip()
    return {n for n in out.split(",") if n}


def test_import_swarm_sdk_does_not_load_polars() -> None:
    assert "polars" not in _loaded_after_import("polars")


def test_import_swarm_sdk_does_not_load_embedding_backends() -> None:
    assert not _loaded_after_import("fastembed", "llama_cpp")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest Agents/tests/test_import_laziness.py -q --tb=short`
Expected: `test_import_swarm_sdk_does_not_load_polars` FAILS (`polars` is loaded); the embedding-backend test PASSES already (it is a regression guard).

- [ ] **Step 3: Implement** — in `observability/usage.py` delete the top-level `import polars as pl` and add it inside `summary()` after the empty check:

```python
        if not self._rows:
            return []
        import polars as pl

        frame = pl.DataFrame(self._rows)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run --extra dev pytest Agents/tests/test_import_laziness.py Agents/tests/test_tokens.py -q --tb=short`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run --extra dev ruff check src/swarm_sdk/observability/usage.py Agents/tests/test_import_laziness.py
git add src/swarm_sdk/observability/usage.py Agents/tests/test_import_laziness.py
git commit -m "perf: load polars lazily, guard heavy imports" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `UsageLog` latency, model and cost estimate

**Files:**
- Modify: `src/swarm_sdk/observability/usage.py`
- Test: `Agents/tests/test_tokens.py`

**Interfaces:**
- Produces: `UsageLog.add(agent: str, tokens: int, cached: bool, *, latency_ms: float = 0.0, model: str = "") -> None`; `UsageLog.summary() -> list[dict[str, object]]` rows now `{"agent", "tokens", "latency_ms_total", "cost_estimate_usd"}`. `MODEL_RATES_USD_PER_1K: dict[str, tuple[float, float]]`, `estimate_cost_usd(model: str, tokens: int) -> float`.

- [ ] **Step 1: Write the failing tests**

```python
from swarm_sdk.observability.usage import UsageLog, estimate_cost_usd


def test_usage_add_new_kwargs_are_optional() -> None:
    log = UsageLog()
    log.add("coder", 10, False)
    rows = log.summary()
    assert rows == [
        {"agent": "coder", "tokens": 10, "latency_ms_total": 0.0, "cost_estimate_usd": 0.0}
    ]


def test_usage_summary_sums_latency_and_cost() -> None:
    log = UsageLog()
    log.add("coder", 1000, False, latency_ms=12.5, model="openai:gpt-4o-mini")
    log.add("coder", 1000, False, latency_ms=7.5, model="openai:gpt-4o-mini")
    (row,) = log.summary()
    assert row["tokens"] == 2000
    assert row["latency_ms_total"] == 20.0
    assert row["cost_estimate_usd"] > 0.0


def test_estimate_cost_unknown_model_is_zero() -> None:
    assert estimate_cost_usd("nope:model", 5000) == 0.0
    assert estimate_cost_usd("", 5000) == 0.0
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest Agents/tests/test_tokens.py -q --tb=short -k usage`
Expected: FAIL with `ImportError: cannot import name 'estimate_cost_usd'`.

- [ ] **Step 3: Implement** — replace `usage.py` body:

```python
"""Token-usage rollups with Polars."""

from __future__ import annotations

# (input, output) USD per 1k tokens. Usage rows only carry a total, so the
# blended rate is the mean; unknown models cost 0.0 and never raise.
MODEL_RATES_USD_PER_1K: dict[str, tuple[float, float]] = {
    "openai:gpt-4o-mini": (0.00015, 0.0006),
    "openai:gpt-4o": (0.0025, 0.01),
}


def estimate_cost_usd(model: str, tokens: int) -> float:
    """Return an approximate USD cost for ``tokens`` on ``model`` (0.0 if unknown)."""
    rates = MODEL_RATES_USD_PER_1K.get(model)
    if rates is None:
        return 0.0
    return (tokens / 1000.0) * (rates[0] + rates[1]) / 2.0


class UsageLog:
    """Accumulate per-agent token rows and summarize with Polars."""

    def __init__(self) -> None:
        """Create an empty usage log."""
        self._rows: list[dict[str, object]] = []

    def add(
        self,
        agent: str,
        tokens: int,
        cached: bool,
        *,
        latency_ms: float = 0.0,
        model: str = "",
    ) -> None:
        """Record one usage event.

        Args:
            agent: Agent or subsystem name (e.g. ``"coder"``, ``"cache"``).
            tokens: Tokens charged to that agent for this event.
            cached: Whether the response came from the semantic cache.
            latency_ms: Wall time for the event in milliseconds.
            model: Model name used for the cost estimate (may be empty).
        """
        self._rows.append(
            {
                "agent": agent,
                "tokens": tokens,
                "cached": cached,
                "latency_ms": latency_ms,
                "cost_usd": estimate_cost_usd(model, tokens),
            }
        )

    def summary(self) -> list[dict[str, object]]:
        """Sum tokens, latency and estimated cost per agent, sorted by agent name.

        Returns:
            Rows of ``agent``, ``tokens``, ``latency_ms_total``, ``cost_estimate_usd``,
            or ``[]`` when empty.
        """
        if not self._rows:
            return []
        import polars as pl

        frame = pl.DataFrame(self._rows)
        grouped = frame.group_by("agent").agg(
            pl.col("tokens").sum().alias("tokens"),
            pl.col("latency_ms").sum().alias("latency_ms_total"),
            pl.col("cost_usd").sum().alias("cost_estimate_usd"),
        )
        return grouped.sort("agent").to_dicts()
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run --extra dev pytest Agents/tests/test_tokens.py Agents/tests/test_swarm.py -q --tb=short`
Expected: PASS. If an existing test asserts the old two-key summary shape, update that assertion to include the two new keys (behavior change is intended by the spec) and say so in the commit body.

- [ ] **Step 5: Commit**

```bash
uv run --extra dev ruff check src/swarm_sdk/observability/usage.py
git add src/swarm_sdk/observability/usage.py Agents/tests/test_tokens.py
git commit -m "feat: track latency and estimated cost in UsageLog" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Prometheus metrics module (no-op without the dependency)

**Files:**
- Create: `src/swarm_sdk/observability/metrics.py`
- Modify: `pyproject.toml` (`observability` extra), `src/swarm_sdk/observability/__init__.py`
- Test: `Agents/tests/test_observability.py` (new)

**Interfaces:**
- Produces: `metrics.ENABLED: bool`; `metrics.record_request(mode: str, cached: bool) -> None`; `metrics.record_tokens(agent: str, model: str, tokens: int) -> None`; `metrics.record_cache_hit(kind: str) -> None` (`"exact" | "semantic"`); `metrics.observe_step(step: str, seconds: float) -> None`; `metrics.set_active_threads(n: int) -> None`. All are no-ops when `prometheus_client` is missing.

- [ ] **Step 1: Write the failing test** (`Agents/tests/test_observability.py`)

```python
"""Metrics and tracing helpers are safe to call with or without their extras."""

from __future__ import annotations

from swarm_sdk.observability import metrics


def test_metrics_calls_never_raise() -> None:
    metrics.record_request("swarm", False)
    metrics.record_tokens("coder", "openai:gpt-4o-mini", 12)
    metrics.record_cache_hit("exact")
    metrics.observe_step("route", 0.01)
    metrics.set_active_threads(3)


def test_metrics_enabled_matches_import() -> None:
    try:
        import prometheus_client  # noqa: F401
    except ImportError:
        assert metrics.ENABLED is False
    else:
        assert metrics.ENABLED is True
```

The `# noqa: F401` names rule F401 (unused import) and the reason is that the import is the probe. That is allowed by the repo rule.

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest Agents/tests/test_observability.py -q --tb=short`
Expected: FAIL with `ImportError: cannot import name 'metrics'`.

- [ ] **Step 3: Implement**

`src/swarm_sdk/observability/metrics.py`:

```python
"""Prometheus instruments. Every function is a no-op without ``prometheus-client``."""

from __future__ import annotations

try:
    from prometheus_client import Counter, Gauge, Histogram
except ImportError:
    ENABLED = False
else:
    ENABLED = True
    _REQUESTS = Counter("swarm_requests_total", "Swarm runs", ["mode", "cached"])
    _TOKENS = Counter("swarm_token_usage_total", "Tokens charged", ["agent", "model"])
    _CACHE_HITS = Counter("swarm_cache_hits_total", "Cache hits", ["kind"])
    _STEP_SECONDS = Histogram("swarm_step_latency_seconds", "Step latency", ["step"])
    _THREADS = Gauge("swarm_active_threads", "Tracked conversation threads")


def record_request(mode: str, cached: bool) -> None:
    if ENABLED:
        _REQUESTS.labels(mode=mode, cached=str(cached).lower()).inc()


def record_tokens(agent: str, model: str, tokens: int) -> None:
    if ENABLED and tokens > 0:
        _TOKENS.labels(agent=agent, model=model or "unknown").inc(tokens)


def record_cache_hit(kind: str) -> None:
    if ENABLED:
        _CACHE_HITS.labels(kind=kind).inc()


def observe_step(step: str, seconds: float) -> None:
    if ENABLED:
        _STEP_SECONDS.labels(step=step).observe(seconds)


def set_active_threads(count: int) -> None:
    if ENABLED:
        _THREADS.set(count)


__all__ = [
    "ENABLED",
    "observe_step",
    "record_cache_hit",
    "record_request",
    "record_tokens",
    "set_active_threads",
]
```

`pyproject.toml`, in `[project.optional-dependencies] observability`, add `"prometheus-client>=0.20",` (PyPI-verify the package exists first: `curl -s -o /dev/null -w '%{http_code}' https://pypi.org/pypi/prometheus-client/json` must print `200`). Then `uv lock`.

`observability/__init__.py`: keep `UsageLog` export; add `"metrics"` is unnecessary since modules import by path.

- [ ] **Step 4: Run to verify pass**

Run: `uv run --extra dev pytest Agents/tests/test_observability.py -q --tb=short` then `uv run --extra dev --extra observability pytest Agents/tests/test_observability.py -q --tb=short`
Expected: PASS in both (the second confirms `ENABLED is True` with the extra).

- [ ] **Step 5: Commit**

```bash
uv run --extra dev ruff check src/swarm_sdk/observability Agents/tests/test_observability.py
git add src/swarm_sdk/observability/metrics.py pyproject.toml uv.lock Agents/tests/test_observability.py
git commit -m "feat: optional Prometheus metrics" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: OpenTelemetry span helper (no-op without the dependency)

**Files:**
- Create: `src/swarm_sdk/observability/tracing.py`
- Test: `Agents/tests/test_observability.py`

**Interfaces:**
- Produces: `tracing.span(name: str, **attrs: str | int | float | bool) -> contextlib.AbstractContextManager[None]`. Works as a plain `with`. Exceptions inside propagate unchanged and are recorded on the span when OTel is active.

- [ ] **Step 1: Write the failing tests** (append)

```python
import pytest

from swarm_sdk.observability import tracing


def test_span_is_a_noop_context_manager() -> None:
    with tracing.span("swarm.run", mode="swarm", cached=False):
        value = 1 + 1
    assert value == 2


def test_span_propagates_exceptions() -> None:
    with pytest.raises(ValueError, match="boom"):
        with tracing.span("swarm.run"):
            raise ValueError("boom")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest Agents/tests/test_observability.py -q --tb=short -k span`
Expected: FAIL with `ImportError: cannot import name 'tracing'`.

- [ ] **Step 3: Implement**

```python
"""OpenTelemetry spans. A no-op unless ``opentelemetry-api`` is installed."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

try:
    from opentelemetry import trace
except ImportError:
    _TRACER = None
else:
    _TRACER = trace.get_tracer("swarm_sdk")


@contextmanager
def span(name: str, **attrs: str | int | float | bool) -> Iterator[None]:
    """Open a span named ``name`` with scalar attributes; no-op without OTel."""
    if _TRACER is None:
        yield
        return
    with _TRACER.start_as_current_span(name, attributes=attrs) as active:
        try:
            yield
        except BaseException as exc:
            active.record_exception(exc)
            raise
```

Never put prompt text or secrets in `attrs`; callers pass scalars such as `mode`, `cached`.

- [ ] **Step 4: Run to verify pass**

Run: `uv run --extra dev pytest Agents/tests/test_observability.py -q --tb=short` and again with `--extra observability`.
Expected: PASS in both.

- [ ] **Step 5: Commit**

```bash
uv run --extra dev ruff check src/swarm_sdk/observability/tracing.py Agents/tests/test_observability.py
git add src/swarm_sdk/observability/tracing.py Agents/tests/test_observability.py
git commit -m "feat: optional OpenTelemetry span helper" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 6: WAL mode for both SQLite stores

**Files:**
- Modify: `src/swarm_sdk/memory/sqlite_vec.py` (after `sqlite3.connect`, line ~29), `src/swarm_sdk/retrieval/cache.py` (after `sqlite3.connect`, line ~28)
- Test: `Agents/tests/test_memory.py`, `Agents/tests/test_swarm.py`

**Interfaces:**
- Produces: both stores open with `PRAGMA journal_mode=WAL` for file-backed databases. `:memory:` databases are left alone (SQLite reports `memory` and that is fine).

- [ ] **Step 1: Write the failing tests**

In `Agents/tests/test_memory.py`:

```python
def test_sqlite_store_uses_wal(tmp_path: Path) -> None:
    from swarm_sdk.memory.sqlite_vec import SqliteVecStore

    store = SqliteVecStore(str(tmp_path / "m.db"), 8)
    mode = store._conn.execute("PRAGMA journal_mode").fetchone()[0]
    store.close()
    assert mode.lower() == "wal"
```

In `Agents/tests/test_swarm.py`:

```python
def test_semantic_cache_uses_wal(tmp_path: Path) -> None:
    cache = SemanticCache(str(tmp_path / "c.db"), HashEmbedder(16))
    assert cache._conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest Agents/tests/test_memory.py Agents/tests/test_swarm.py -q --tb=short -k wal`
Expected: FAIL (`'delete' == 'wal'`).

- [ ] **Step 3: Implement** — immediately after each `self._conn = sqlite3.connect(...)` line add:

```python
        self._conn.execute("PRAGMA journal_mode=WAL")
```

`sqlite_vec.py` and `test_memory.py` carry unrelated uncommitted edits: run `git diff src/swarm_sdk/memory/sqlite_vec.py Agents/tests/test_memory.py`, and stage only your hunks with `git add -p`.

- [ ] **Step 4: Run to verify pass**

Run: `uv run --extra dev pytest Agents/tests/test_memory.py Agents/tests/test_swarm.py -q --tb=short`
Expected: PASS (existing tests confirm WAL does not break them).

- [ ] **Step 5: Commit**

```bash
uv run --extra dev ruff check src/swarm_sdk/memory/sqlite_vec.py src/swarm_sdk/retrieval/cache.py
git add -p src/swarm_sdk/memory/sqlite_vec.py Agents/tests/test_memory.py
git add src/swarm_sdk/retrieval/cache.py Agents/tests/test_swarm.py
git commit -m "perf: open SQLite stores in WAL mode" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 7: `Settings` fields and `SemanticCache` TTL eviction

**Files:**
- Modify: `src/swarm_sdk/config/settings.py`, `src/swarm_sdk/retrieval/cache.py`, `src/swarm_sdk/core/swarm.py` (the `cache` property, line ~187)
- Test: `Agents/tests/test_swarm.py`, `Agents/tests/test_config.py`

**Interfaces:**
- Produces: `Settings.opencl_quantize: Literal["none","int8","binary"] = "none"`, `Settings.semantic_cache_on_gpu: bool = False`, `Settings.cache_ttl_days: int | None = None` (`ge=1`), `Settings.router_structured_output: bool = True`. `SemanticCache(path, embedder, threshold=0.97, *, ttl_days: int | None = None, use_index: bool = False)`. This task wires `ttl_days`; `use_index` is consumed in Task 12.
- Both tables gain `inserted_at REAL`; legacy databases are migrated with `ALTER TABLE ... ADD COLUMN`.

- [ ] **Step 1: Write the failing tests**

`Agents/tests/test_config.py`:

```python
def test_new_settings_defaults_preserve_behavior() -> None:
    from swarm_sdk.config.settings import Settings

    s = Settings()
    assert s.opencl_quantize == "none"
    assert s.semantic_cache_on_gpu is False
    assert s.cache_ttl_days is None
    assert s.router_structured_output is True
```

`Agents/tests/test_swarm.py`:

```python
import sqlite3
import time


def test_semantic_cache_ttl_evicts_old_rows(tmp_path: Path) -> None:
    path = str(tmp_path / "c.db")
    embedder = HashEmbedder(16)
    cache = SemanticCache(path, embedder)
    cache.store("old question", "old answer")
    cache._conn.execute("UPDATE exact_cache SET inserted_at = ?", (time.time() - 10 * 86400,))
    cache._conn.execute("UPDATE semantic_cache SET inserted_at = ?", (time.time() - 10 * 86400,))
    cache._conn.commit()
    cache._conn.close()

    fresh = SemanticCache(path, embedder, ttl_days=1)
    assert fresh.lookup("old question") is None


def test_semantic_cache_ttl_none_keeps_rows(tmp_path: Path) -> None:
    path = str(tmp_path / "c.db")
    embedder = HashEmbedder(16)
    SemanticCache(path, embedder).store("q", "a")
    assert SemanticCache(path, embedder).lookup("q") == "a"


def test_semantic_cache_migrates_legacy_schema(tmp_path: Path) -> None:
    path = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE exact_cache (key TEXT PRIMARY KEY, response TEXT NOT NULL)")
    conn.execute(
        "CREATE TABLE semantic_cache (id INTEGER PRIMARY KEY, vector BLOB NOT NULL, "
        "response TEXT NOT NULL)"
    )
    conn.commit()
    conn.close()
    cache = SemanticCache(path, HashEmbedder(16), ttl_days=7)
    cache.store("q", "a")
    assert cache.lookup("q") == "a"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest Agents/tests/test_config.py Agents/tests/test_swarm.py -q --tb=short -k "new_settings or ttl or legacy"`
Expected: FAIL (`AttributeError`/`TypeError: unexpected keyword 'ttl_days'`).

- [ ] **Step 3: Implement**

`settings.py`: add after `opencl_enabled`:

```python
    opencl_quantize: Literal["none", "int8", "binary"] = "none"
    semantic_cache_on_gpu: bool = False
    cache_ttl_days: int | None = Field(default=None, ge=1)
    router_structured_output: bool = True
```

`cache.py`: add `import time` and change `__init__`:

```python
    def __init__(
        self,
        path: str,
        embedder: Embedder,
        threshold: float = 0.97,
        *,
        ttl_days: int | None = None,
        use_index: bool = False,
    ) -> None:
        self.embedder = embedder
        self.threshold = threshold
        self.ttl_days = ttl_days
        self.use_index = use_index
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        # (keep the two CREATE TABLE statements, adding ", inserted_at REAL" to each)
        for table in ("exact_cache", "semantic_cache"):
            columns = {row[1] for row in self._conn.execute(f"PRAGMA table_info({table})")}
            if "inserted_at" not in columns:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN inserted_at REAL")
        if ttl_days is not None:
            cutoff = time.time() - ttl_days * 86400
            for table in ("exact_cache", "semantic_cache"):
                self._conn.execute(
                    f"DELETE FROM {table} WHERE inserted_at IS NOT NULL AND inserted_at < ?",
                    (cutoff,),
                )
        self._conn.commit()
```

Rows written by the old code have `inserted_at IS NULL`; they are kept, never evicted, because their age is unknown. `store()` must write `inserted_at`: change both INSERTs to include `inserted_at` with `time.time()`. The table names in the f-strings come from a fixed tuple, not user input.

`core/swarm.py` `cache` property: pass `ttl_days=self.settings.cache_ttl_days`.

- [ ] **Step 4: Run to verify pass**

Run: `uv run --extra dev pytest Agents/tests/test_config.py Agents/tests/test_swarm.py -q --tb=short`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run --extra dev ruff check src/swarm_sdk/config/settings.py src/swarm_sdk/retrieval/cache.py src/swarm_sdk/core/swarm.py
git add src/swarm_sdk/config/settings.py src/swarm_sdk/retrieval/cache.py src/swarm_sdk/core/swarm.py Agents/tests/test_config.py Agents/tests/test_swarm.py
git commit -m "feat: cache TTL eviction and new opt-in settings" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 8: OpenCL kernels `normalize_dot` and INT8 (`quantize_int8`, `dequant_dot`)

**Files:**
- Modify: `src/swarm_sdk/gpu/opencl_math.py` (`_SOURCE`, kernel tuple at line ~123, new functions after `batch_cosine`), `src/swarm_sdk/gpu/__init__.py`
- Test: `Agents/tests/test_gpu_math.py`

**Interfaces:**
- Produces:
  - `normalize_dot(query: np.ndarray, vectors: np.ndarray) -> np.ndarray` (float32 scores; cosine of `query` against every row; zero-norm rows score 0).
  - `quantize_int8(matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray]`: `(int8 matrix shape (rows, cols), float32 scales shape (rows,))`, symmetric: `scale = max(|row|)/127`, all-zero row gets scale `1.0` and zero codes.
  - `dequant_dot(int8_matrix: np.ndarray, scales: np.ndarray, query: np.ndarray) -> np.ndarray` (float32 scores = `(int8 * scale) @ query`).
- All three follow the existing pattern: `_use_gpu(rows)` decides; otherwise a NumPy path. The tests below run on the NumPy path (the file's autouse fixture disables OpenCL), which pins the reference semantics the kernels must match.

- [ ] **Step 1: Write the failing tests** (append to `test_gpu_math.py`; import the new names)

```python
from swarm_sdk.gpu import dequant_dot, normalize_dot, quantize_int8


def test_normalize_dot_matches_cosine() -> None:
    m = _random_matrix(20, 16)
    q = _random_matrix(1, 16)[0]
    np.testing.assert_allclose(normalize_dot(q, m), batch_cosine(q, m), rtol=1e-5, atol=1e-6)


def test_normalize_dot_zero_row_scores_zero() -> None:
    m = np.zeros((2, 4), dtype=np.float32)
    m[1] = [1, 0, 0, 0]
    q = np.array([1, 0, 0, 0], dtype=np.float32)
    scores = normalize_dot(q, m)
    assert scores[0] == 0.0
    assert scores[1] == pytest.approx(1.0)


def test_quantize_int8_roundtrip_error_is_small() -> None:
    m = _random_matrix(30, 32)
    codes, scales = quantize_int8(m)
    assert codes.dtype == np.int8 and scales.dtype == np.float32
    assert codes.shape == m.shape and scales.shape == (30,)
    restored = codes.astype(np.float32) * scales[:, None]
    assert np.max(np.abs(restored - m)) <= np.max(np.abs(m)) / 127.0 + 1e-6


def test_quantize_int8_zero_row() -> None:
    codes, scales = quantize_int8(np.zeros((1, 8), dtype=np.float32))
    assert not codes.any()
    assert scales[0] == 1.0


def test_dequant_dot_close_to_float_dot() -> None:
    m = _random_matrix(40, 24)
    q = _random_matrix(1, 24)[0]
    codes, scales = quantize_int8(m)
    exact = m @ q
    approx = dequant_dot(codes, scales, q)
    assert np.max(np.abs(approx - exact)) < 0.15


def test_dequant_dot_single_row() -> None:
    m = _random_matrix(1, 5)
    codes, scales = quantize_int8(m)
    assert dequant_dot(codes, scales, m[0]).shape == (1,)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest Agents/tests/test_gpu_math.py -q --tb=short -k "normalize_dot or int8 or dequant"`
Expected: FAIL with `ImportError: cannot import name 'dequant_dot' from 'swarm_sdk.gpu'`.

- [ ] **Step 3: Implement**

Append to `_SOURCE` (before the closing `"""`):

```c
__kernel void normalize_dot(__global const float *matrix,
                            __global const float *query,
                            __global float *out,
                            const uint rows,
                            const uint cols) {
    uint r = get_global_id(0);
    if (r >= rows) return;
    float dot = 0.0f;
    float sq = 0.0f;
    for (uint c = 0; c < cols; c++) {
        float v = matrix[r * cols + c];
        dot += v * query[c];
        sq += v * v;
    }
    out[r] = sq > 0.0f ? dot * rsqrt(sq) : 0.0f;
}

__kernel void quantize_int8(__global const float *matrix,
                            __global char *out_codes,
                            __global float *out_scale,
                            const uint rows,
                            const uint cols) {
    uint r = get_global_id(0);
    if (r >= rows) return;
    float peak = 0.0f;
    for (uint c = 0; c < cols; c++) peak = fmax(peak, fabs(matrix[r * cols + c]));
    float scale = peak > 0.0f ? peak / 127.0f : 1.0f;
    out_scale[r] = scale;
    for (uint c = 0; c < cols; c++) {
        float q = rint(matrix[r * cols + c] / scale);
        out_codes[r * cols + c] = (char)clamp(q, -127.0f, 127.0f);
    }
}

__kernel void dequant_dot(__global const char *codes,
                          __global const float *scales,
                          __global const float *query,
                          __global float *out,
                          const uint rows,
                          const uint cols) {
    uint r = get_global_id(0);
    if (r >= rows) return;
    float sum = 0.0f;
    for (uint c = 0; c < cols; c++) sum += (float)codes[r * cols + c] * query[c];
    out[r] = sum * scales[r];
}
```

Extend the kernel-name tuple at `opencl_math.py:123` to include `"normalize_dot", "quantize_int8", "dequant_dot"`.

Add Python (after `batch_cosine`). The NumPy path is the reference and must be written first:

```python
def normalize_dot(query: np.ndarray, vectors: np.ndarray) -> np.ndarray:
    """Cosine of ``query`` with every row in one pass; zero-norm rows score 0."""
    query = _ensure_f32_contiguous(query, "query").reshape(-1)
    matrix = _ensure_f32_contiguous(vectors, "vectors").reshape(-1, query.shape[0])
    if not _use_gpu(matrix.shape[0]):
        norms = np.linalg.norm(matrix, axis=1)
        dots = matrix @ query
        return np.where(norms > 0, dots / np.where(norms > 0, norms, 1.0), 0.0).astype(np.float32)
    return _run_row_kernel("normalize_dot", matrix, query)


def quantize_int8(matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Symmetric per-row INT8 quantization: ``scale = max(|row|) / 127``."""
    m = _ensure_f32_contiguous(matrix, "matrix")
    if m.ndim == 1:
        m = m.reshape(1, -1)
    peak = np.abs(m).max(axis=1)
    scales = np.where(peak > 0, peak / 127.0, 1.0).astype(np.float32)
    codes = np.clip(np.rint(m / scales[:, None]), -127, 127).astype(np.int8)
    return codes, scales


def dequant_dot(int8_matrix: np.ndarray, scales: np.ndarray, query: np.ndarray) -> np.ndarray:
    """Scores of ``query`` against INT8 rows without materializing a float32 matrix on the GPU."""
    query = _ensure_f32_contiguous(query, "query").reshape(-1)
    codes = np.ascontiguousarray(int8_matrix, dtype=np.int8).reshape(-1, query.shape[0])
    scale = np.asarray(scales, dtype=np.float32).reshape(-1)
    if not _use_gpu(codes.shape[0]):
        return ((codes.astype(np.float32) @ query) * scale).astype(np.float32)
    return _run_int8_kernel(codes, scale, query)
```

`_run_row_kernel` and `_run_int8_kernel` are small private helpers that allocate buffers exactly like `batch_dot` does (`READ_ONLY | COPY_HOST_PTR` for inputs, `WRITE_ONLY` output, `enqueue_copy`, `queue.finish()`); `_run_row_kernel(name, matrix, query)` launches `(rows,)` work-items with args `(matrix, query, out, rows, cols)`, and `_run_int8_kernel(codes, scales, query)` passes `(codes, scales, query, out, rows, cols)`. Write both as ordinary functions in this file; each is about ten lines mirroring `batch_dot`. The GPU path is verified in Task 21's benchmark on the Radeon, not in CI; the CI-safe contract is the NumPy path above.

`quantize_int8` stays NumPy-only and has **no** OpenCL kernel: quantization runs once per insert on small batches where transfer cost dominates, and an undispatched kernel is dead code. So do not add the `quantize_int8` kernel source shown above to `_SOURCE` or the kernel-name tuple; add only `normalize_dot` and `dequant_dot`. This narrows the spec (which listed a `quantize_int8` kernel); see Deviations.

Export from `gpu/__init__.py`: add `dequant_dot`, `normalize_dot`, `quantize_int8` to the import list and `__all__`.

- [ ] **Step 4: Run to verify pass**

Run: `uv run --extra dev pytest Agents/tests/test_gpu_math.py -q --tb=short`
Expected: PASS. Then, on this Mac only, smoke the kernels compile: `SWARM_OPENCL_MIN_ROWS=1 uv run --extra dev --extra opencl python -c "from swarm_sdk.gpu import opencl_status; print(opencl_status())"` and expect `available: True` with no `OpenCL init failed` error. If pyopencl is not installed, report that the GPU path was not run.

- [ ] **Step 5: Commit**

```bash
uv run --extra dev ruff check src/swarm_sdk/gpu Agents/tests/test_gpu_math.py
git add src/swarm_sdk/gpu/opencl_math.py src/swarm_sdk/gpu/__init__.py Agents/tests/test_gpu_math.py
git commit -m "feat(gpu): fused normalize_dot and INT8 quantize/dequant_dot" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 9: OpenCL binary kernels (`binary_quantize`, `binary_dot`) and `batch_softmax`

**Files:**
- Modify: `src/swarm_sdk/gpu/opencl_math.py`, `src/swarm_sdk/gpu/__init__.py`
- Test: `Agents/tests/test_gpu_math.py`

**Interfaces:**
- Produces:
  - `binary_quantize(matrix: np.ndarray) -> np.ndarray`: packed `uint32` array shape `(rows, ceil(cols/32))`; bit `j` of word `w` is `1` when `matrix[r, 32*w + j] >= 0`. Padding bits are `0`.
  - `binary_dot(bits_matrix: np.ndarray, query_bits: np.ndarray, *, dim: int) -> np.ndarray`: float32 similarity in `[0, dim]`, `dim - hamming_distance`, **higher is more similar**. `dim` is required so padding bits never count.
  - `batch_softmax(scores: np.ndarray) -> np.ndarray`: float32, numerically stable, sums to 1.

- [ ] **Step 1: Write the failing tests**

```python
from swarm_sdk.gpu import batch_softmax, binary_dot, binary_quantize


def test_binary_quantize_packs_signs() -> None:
    m = np.array([[1.0, -1.0, 0.0, -0.5] + [1.0] * 28 + [-1.0]], dtype=np.float32)  # 33 cols
    bits = binary_quantize(m)
    assert bits.dtype == np.uint32 and bits.shape == (1, 2)
    assert bits[0, 0] & 1 == 1  # +1
    assert (bits[0, 0] >> 1) & 1 == 0  # -1
    assert (bits[0, 0] >> 2) & 1 == 1  # 0.0 counts as non-negative
    assert bits[0, 1] == 0  # the 33rd value is negative; padding is zero


def test_binary_dot_identical_is_dim() -> None:
    m = _random_matrix(5, 40)
    bits = binary_quantize(m)
    scores = binary_dot(bits, bits[2], dim=40)
    assert scores[2] == 40.0
    assert scores.argmax() == 2


def test_binary_dot_opposite_is_zero() -> None:
    v = np.linspace(-1, 1, 33, dtype=np.float32).reshape(1, -1)
    v[v == 0] = 0.5
    assert binary_dot(binary_quantize(v), binary_quantize(-v)[0], dim=33)[0] == 0.0


def test_binary_dot_dim_not_multiple_of_32_ignores_padding() -> None:
    m = np.ones((1, 5), dtype=np.float32)
    bits = binary_quantize(m)
    assert binary_dot(bits, bits[0], dim=5)[0] == 5.0


def test_binary_dot_preserves_neighbor_order() -> None:
    rng = np.random.default_rng(3)
    base = rng.standard_normal((1, 256)).astype(np.float32)
    near = base + 0.05 * rng.standard_normal((1, 256)).astype(np.float32)
    far = rng.standard_normal((1, 256)).astype(np.float32)
    bits = binary_quantize(np.vstack([far, near]))
    scores = binary_dot(bits, binary_quantize(base)[0], dim=256)
    assert scores[1] > scores[0]


def test_batch_softmax_sums_to_one_and_is_stable() -> None:
    scores = np.array([1000.0, 1001.0, 999.0], dtype=np.float32)
    p = batch_softmax(scores)
    assert p.sum() == pytest.approx(1.0, abs=1e-6)
    assert p.argmax() == 1
    assert np.isfinite(p).all()


def test_batch_softmax_single_and_empty() -> None:
    assert batch_softmax(np.array([3.0], dtype=np.float32))[0] == pytest.approx(1.0)
    assert batch_softmax(np.array([], dtype=np.float32)).size == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest Agents/tests/test_gpu_math.py -q --tb=short -k "binary or softmax"`
Expected: FAIL with `ImportError: cannot import name 'binary_quantize'`.

- [ ] **Step 3: Implement**

NumPy reference (this is the CI-tested path):

```python
def binary_quantize(matrix: np.ndarray) -> np.ndarray:
    """Pack sign bits (``>= 0`` is 1) into ``uint32`` words, 32 columns per word."""
    m = np.asarray(matrix, dtype=np.float32)
    if m.ndim == 1:
        m = m.reshape(1, -1)
    rows, cols = m.shape
    words = (cols + 31) // 32
    padded = np.zeros((rows, words * 32), dtype=np.uint8)
    padded[:, :cols] = m >= 0
    packed = np.packbits(padded.reshape(rows, words, 32), axis=2, bitorder="little")
    return packed.view(np.uint32).reshape(rows, words)


def binary_dot(bits_matrix: np.ndarray, query_bits: np.ndarray, *, dim: int) -> np.ndarray:
    """``dim - hamming_distance`` per row; higher means more similar."""
    bits = np.ascontiguousarray(bits_matrix, dtype=np.uint32)
    query = np.ascontiguousarray(query_bits, dtype=np.uint32).reshape(-1)
    if bits.shape[1] != query.shape[0]:
        raise ValueError("query words must match matrix words")
    xor = np.bitwise_xor(bits, query[None, :])
    distance = np.unpackbits(xor.view(np.uint8), axis=1).sum(axis=1)
    return (dim - distance).astype(np.float32)


def batch_softmax(scores: np.ndarray) -> np.ndarray:
    """Numerically stable softmax over a 1-D score vector."""
    s = np.asarray(scores, dtype=np.float32).reshape(-1)
    if s.size == 0:
        return s
    e = np.exp(s - s.max())
    return (e / e.sum()).astype(np.float32)
```

Padding safety: `binary_quantize` sets padding bits to 0 for both matrix and query, so they XOR to 0 and add nothing to the distance; `dim` is still required so the returned upper bound is right.

OpenCL kernels (added to `_SOURCE` and the kernel-name tuple; dispatched only when `_use_gpu(rows)`; the CI tests above pin the NumPy path):

```c
__kernel void binary_dot(__global const uint *bits,
                         __global const uint *query,
                         __global float *out,
                         const uint rows,
                         const uint words,
                         const uint dim) {
    uint r = get_global_id(0);
    if (r >= rows) return;
    uint distance = 0;
    for (uint w = 0; w < words; w++) distance += popcount(bits[r * words + w] ^ query[w]);
    out[r] = (float)dim - (float)distance;
}
```

`binary_quantize` and `batch_softmax` stay NumPy-only: softmax runs over at most `retrieve_k` (default 20) scores where GPU dispatch cannot win, and quantization is a one-off at insert time. The spec listed GPU kernels for both; this narrows it, backed by the threshold logic already in `_gpu_threshold()` (8192 rows). Record the measured crossover in Task 21 before deciding otherwise. `binary_dot` dispatch: when `_use_gpu(rows)` call a `_run_binary_kernel(bits, query, dim)` helper written like the other buffer helpers.

Export `batch_softmax`, `binary_dot`, `binary_quantize` from `gpu/__init__.py`.

- [ ] **Step 4: Run to verify pass**

Run: `uv run --extra dev pytest Agents/tests/test_gpu_math.py -q --tb=short`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run --extra dev ruff check src/swarm_sdk/gpu Agents/tests/test_gpu_math.py
git add src/swarm_sdk/gpu/opencl_math.py src/swarm_sdk/gpu/__init__.py Agents/tests/test_gpu_math.py
git commit -m "feat(gpu): binary quantization, Hamming similarity and stable softmax" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 10: `OpenClVecStore(quantize=...)`

**Files:**
- Modify: `src/swarm_sdk/memory/opencl_store.py`
- Test: `Agents/tests/test_memory.py`

**Interfaces:**
- Consumes: `quantize_int8`, `dequant_dot`, `binary_quantize`, `binary_dot` from Task 8/9.
- Produces: `OpenClVecStore(dim, *, max_vectors=4096, chunk_rows=256, quantize: Literal["none","int8","binary"] = "none")`. `resident_bytes` reports the quantized footprint. Public `add`/`search` signatures unchanged.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("mode", ["none", "int8", "binary"])
def test_quantized_store_finds_exact_neighbor(mode: str) -> None:
    store = OpenClVecStore(dim=64, quantize=mode)
    rng = np.random.default_rng(1)
    vectors = rng.standard_normal((50, 64)).astype(np.float32)
    for i, v in enumerate(vectors):
        store.add(f"t{i}", v)
    hits = store.search(vectors[7], 1)
    assert hits[0].text == "t7"


def test_quantized_store_uses_less_memory() -> None:
    def filled(mode: str) -> int:
        s = OpenClVecStore(dim=256, quantize=mode)
        for i in range(64):
            s.add(str(i), np.random.default_rng(i).standard_normal(256).astype(np.float32))
        return s.resident_bytes

    none, int8, binary = filled("none"), filled("int8"), filled("binary")
    assert int8 < none / 3
    assert binary < int8 / 4


def test_binary_store_ring_buffer_keeps_ids_and_texts_aligned() -> None:
    store = OpenClVecStore(dim=32, max_vectors=3, chunk_rows=1, quantize="binary")
    rng = np.random.default_rng(5)
    vecs = [rng.standard_normal(32).astype(np.float32) for _ in range(5)]
    ids = [store.add(f"t{i}", v) for i, v in enumerate(vecs)]
    hit = store.search(vecs[4], 1)[0]
    assert hit.text == "t4"
    assert hit.id == ids[4]


def test_store_rejects_unknown_quantize_mode() -> None:
    with pytest.raises(ValueError):
        OpenClVecStore(dim=4, quantize="fp4")  # type: ignore[arg-type]
```

The `# type: ignore[arg-type]` names a rule and the reason (deliberately invalid value) is stated by the test name. Keep it.

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest Agents/tests/test_memory.py -q --tb=short -k quantized`
Expected: FAIL with `TypeError: unexpected keyword argument 'quantize'`.

- [ ] **Step 3: Implement** (`test_memory.py` and other files carry unrelated edits; stage only your hunks.)

In `opencl_store.py`:

- Import `Literal` and the four gpu functions.
- `__init__`: add `quantize` kwarg; `if quantize not in ("none","int8","binary"): raise ValueError(...)`. Store `self._mode`. Allocate the backing arrays per mode:
  - `none`: `_vectors` float32 `(cap, dim)` (unchanged).
  - `int8`: `_codes` int8 `(cap, dim)` plus `_scales` float32 `(cap,)`.
  - `binary`: `_bits` uint32 `(cap, ceil(dim/32))`.
- Factor the ring-buffer growth block in `add()` into `_grow(capacity)` that resizes whichever arrays the mode uses, and a `_write_slot(slot, row)` that writes the normalized float row in the mode's representation (`quantize_int8(row)` / `binary_quantize(row)`). Ids and texts stay exactly as today, so alignment is unchanged.
- `search()`: keep the chunk loop; per chunk compute local scores by mode: `none` → existing `topk_ip`; `int8` → `dequant_dot(codes_chunk, scales_chunk, query)` then argpartition top-k; `binary` → `binary_dot(bits_chunk, binary_quantize(query)[0], dim=self.dim)` then top-k. Reuse the existing merge (`np.concatenate`, `argpartition`) untouched.
- `resident_bytes`: sum `nbytes` of the arrays for the active mode.

Keep the `cache_key` passing only for mode `none` (the GPU matrix cache is float32-specific).

- [ ] **Step 4: Run to verify pass**

Run: `uv run --extra dev pytest Agents/tests/test_memory.py Agents/tests/test_swarm.py -q --tb=short`
Expected: PASS, including the pre-existing `OpenClVecStore` tests (default `quantize="none"` must be byte-identical in behavior).

- [ ] **Step 5: Commit**

```bash
uv run --extra dev ruff check src/swarm_sdk/memory/opencl_store.py Agents/tests/test_memory.py
git add src/swarm_sdk/memory/opencl_store.py
git add -p Agents/tests/test_memory.py
git commit -m "feat: INT8 and binary modes for OpenClVecStore" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Config wiring (`quantize`, `structured_output`) and `open_store`

**Files:**
- Modify: `src/swarm_sdk/config/loader.py` (`VectorStoreConfig` line ~61, `RouterConfig` line ~80, `settings_from_file` line ~197), `src/swarm_sdk/core/swarm.py` (`open_store` line ~117), `src/swarm_sdk/agents/config/swarm.yaml`
- Test: `Agents/tests/test_config.py`

**Interfaces:**
- Produces: `VectorStoreConfig.quantize: Literal["none","int8","binary"] = "none"` maps to `Settings.opencl_quantize`; `RouterConfig.structured_output: bool = True` maps to `Settings.router_structured_output`; `open_store(settings)` passes `quantize=settings.opencl_quantize` to `OpenClVecStore`.

- [ ] **Step 1: Write the failing tests**

```python
def test_file_config_maps_quantize_and_structured_output(tmp_path: Path) -> None:
    from swarm_sdk.config.loader import load_settings

    cfg = tmp_path / "s.yaml"
    cfg.write_text(
        "version: 1\nvectorstore:\n  backend: opencl\n  quantize: int8\n"
        "router:\n  structured_output: false\n",
        encoding="utf-8",
    )
    settings, file_cfg = load_settings(cfg)
    assert file_cfg.vectorstore.quantize == "int8"
    assert settings.opencl_quantize == "int8"
    assert settings.router_structured_output is False


def test_open_store_passes_quantize_to_opencl_store() -> None:
    from swarm_sdk.config.settings import Settings
    from swarm_sdk.core.swarm import open_store

    store = open_store(Settings(memory_backend="opencl", embed_dim=64, opencl_quantize="binary"))
    assert store._mode == "binary"


def test_bundled_yaml_still_loads_and_defaults_unchanged() -> None:
    from swarm_sdk.config.loader import load_swarm_config

    cfg = load_swarm_config()
    assert cfg.vectorstore.quantize == "none"
    assert cfg.router.structured_output is True
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest Agents/tests/test_config.py -q --tb=short -k "quantize or open_store or bundled"`
Expected: FAIL (`quantize` is not a field; extra fields are ignored by pydantic `BaseModel` by default, so the assert on `file_cfg.vectorstore.quantize` raises `AttributeError`).

- [ ] **Step 3: Implement**

`loader.py`: add `Literal` import; in `VectorStoreConfig` add `quantize: Literal["none", "int8", "binary"] = "none"  # OpenClVecStore precision`; in `RouterConfig` add `structured_output: bool = True`; in `settings_from_file` updates add `"opencl_quantize": file_cfg.vectorstore.quantize,` and `"router_structured_output": file_cfg.router.structured_output,`.

`core/swarm.py`: `return OpenClVecStore(settings.embed_dim, quantize=settings.opencl_quantize)`.

`swarm.yaml`: under `vectorstore:` add `quantize: none          # OpenClVecStore precision: none | int8 | binary`; under `router:` add `structured_output: true   # ask the provider for JSON; falls back to regex parsing`.

- [ ] **Step 4: Run to verify pass**

Run: `uv run --extra dev pytest Agents/tests/test_config.py Agents/tests/test_swarm.py -q --tb=short && uv run python -m swarm_sdk.agents.validate`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run --extra dev ruff check src/swarm_sdk/config src/swarm_sdk/core/swarm.py
git add src/swarm_sdk/config/loader.py src/swarm_sdk/core/swarm.py src/swarm_sdk/agents/config/swarm.yaml Agents/tests/test_config.py
git commit -m "feat: config knobs for vector quantization and structured routing" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 12: `SemanticCache` GPU-backed index (`use_index`)

**Files:**
- Modify: `src/swarm_sdk/retrieval/cache.py`, `src/swarm_sdk/core/swarm.py` (`cache` property)
- Test: `Agents/tests/test_swarm.py`

**Interfaces:**
- Consumes: `OpenClVecStore` (Task 10), `SemanticCache(..., use_index=...)` (Task 7).
- Produces: with `use_index=True` the cache warms an in-memory `OpenClVecStore` from the newest 256 rows, and `lookup()` calls `store.search(vector, 1)` and compares the score to `threshold` instead of scanning every row. `use_index=False` keeps today's scan, so results must match.

Design notes the implementer needs:
- Vector store payload: `OpenClVecStore.add(text, vector)` stores text; store the **response** as that text. Scores are inner products of unit vectors, i.e. cosine, so the threshold comparison is unchanged.
- The index holds at most 256 recent entries by default (`max_vectors=256`); older rows still live in SQLite and are found only by the exact-match path. State this in the docstring; it is the RAM trade the spec asks for.
- Wrong-dimension blobs in SQLite are skipped during warm-up, same as the current `other.shape == vector.shape` guard.

- [ ] **Step 1: Write the failing tests**

```python
def test_indexed_lookup_matches_scan(tmp_path: Path) -> None:
    embedder = SemanticBucketEmbedder()
    path = str(tmp_path / "c.db")
    seed = SemanticCache(path, embedder, threshold=0.97)
    seed.store("topic alpha", "answer-a")
    seed.store("unrelated words here", "answer-b")

    scan = SemanticCache(path, embedder, threshold=0.97, use_index=False)
    indexed = SemanticCache(path, embedder, threshold=0.97, use_index=True)
    for query in ("topic beta", "unrelated words here", "totally new thing"):
        assert indexed.lookup(query) == scan.lookup(query)


def test_indexed_cache_sees_rows_stored_after_init(tmp_path: Path) -> None:
    embedder = SemanticBucketEmbedder()
    cache = SemanticCache(str(tmp_path / "c.db"), embedder, use_index=True)
    assert cache.lookup("topic one") is None
    cache.store("topic one", "hit")
    assert cache.lookup("topic two") == "hit"


def test_indexed_cache_skips_wrong_dim_blobs(tmp_path: Path) -> None:
    path = str(tmp_path / "c.db")
    SemanticCache(path, HashEmbedder(16)).store("q", "a")
    other = SemanticCache(path, HashEmbedder(32), use_index=True)
    assert other.lookup("something else entirely") is None


def test_indexed_cache_empty_db(tmp_path: Path) -> None:
    assert SemanticCache(str(tmp_path / "c.db"), HashEmbedder(16), use_index=True).lookup("x") is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest Agents/tests/test_swarm.py -q --tb=short -k indexed`
Expected: FAIL. (`use_index` is accepted since Task 7 but does nothing, so `test_indexed_cache_sees_rows_stored_after_init` passes and `test_indexed_cache_skips_wrong_dim_blobs` passes too; the parity tests pass trivially.) If all four already pass, tighten one test to assert the index really exists: add `assert cache._index is not None` to `test_indexed_cache_sees_rows_stored_after_init`, which then FAILS with `AttributeError`.

- [ ] **Step 3: Implement** in `cache.py`:

- `__init__`: `self._index: OpenClVecStore | None = None`; when `use_index`, build `OpenClVecStore(embedder.dim, max_vectors=256)` and warm it: `SELECT vector, response FROM semantic_cache ORDER BY id DESC LIMIT 256`, reverse to oldest-first, skip blobs whose length is not `embedder.dim * 4` bytes, `np.frombuffer(blob, dtype=np.float32)` then `index.add(str(response), vec)`.
- `lookup()`: after the exact-match check and after embedding the query, `if self._index is not None:` do `hits = self._index.search(vector, 1)`; return `hits[0].text` when `hits and hits[0].score >= self.threshold`, else `None`. Otherwise run the existing scan unchanged.
- `store()`: after the SQLite insert, `if self._index is not None: self._index.add(response, vector)`.
- `core/swarm.py` `cache` property: pass `use_index=self.settings.semantic_cache_on_gpu`.

Import `OpenClVecStore` from `swarm_sdk.memory.opencl_store` inside `__init__` (function-local) to avoid an import cycle: `memory.opencl_store` imports `retrieval.embeddings`, and `retrieval.cache` is imported by `core.swarm`.

- [ ] **Step 4: Run to verify pass**

Run: `uv run --extra dev pytest Agents/tests/test_swarm.py -q --tb=short`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run --extra dev ruff check src/swarm_sdk/retrieval/cache.py src/swarm_sdk/core/swarm.py
git add src/swarm_sdk/retrieval/cache.py src/swarm_sdk/core/swarm.py Agents/tests/test_swarm.py
git commit -m "perf: index the semantic cache instead of scanning every row" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Real token usage: `complete_with_usage` and `usage_tokens`

**Files:**
- Modify: `src/swarm_sdk/models/chat.py`, `src/swarm_sdk/models/selection.py` (`FallbackChain`), `src/swarm_sdk/execution/fanout.py`, `src/swarm_sdk/core/swarm.py` (`_route`, `_swarm`)
- Test: `Agents/tests/test_swarm.py`, `Agents/benchmark/Tasks/model_fallback/test_model_fallback.py` (must still pass unchanged)

**Interfaces:**
- Produces:
  - `chat.message_tokens(message: object) -> int | None`: `usage_metadata["total_tokens"]` if present and an int, else `input_tokens + output_tokens` if both ints, else `None`.
  - `chat.usage_tokens(messages: list[object]) -> int | None`: sum of `message_tokens` over AI messages that come **after the last human message**; `None` if none reported. (The checkpointer replays earlier turns; counting them would double-charge.)
  - `async chat.complete_with_usage(model, system, user, *, json_mode: bool = False) -> tuple[str, int]`: token count is the provider's, else `count_text(system) + count_text(user) + count_text(text)`.
  - `complete(model, system, user) -> str` unchanged signature; delegates.
  - `FallbackChain.complete_with_usage(system, user, think_level=None, *, json_mode=False) -> tuple[str, int]`; `FallbackChain.complete(...) -> str` delegates.

- [ ] **Step 1: Write the failing tests**

```python
from langchain_core.messages import AIMessage, HumanMessage

from swarm_sdk.models.chat import complete_with_usage, message_tokens, usage_tokens


def _ai(text: str, total: int | None) -> AIMessage:
    meta = None if total is None else {"input_tokens": 1, "output_tokens": total - 1, "total_tokens": total}
    return AIMessage(content=text, usage_metadata=meta)


def test_message_tokens_reads_total_and_falls_back_to_sum() -> None:
    assert message_tokens(_ai("x", 9)) == 9
    partial = AIMessage(content="x", usage_metadata={"input_tokens": 3, "output_tokens": 4})
    assert message_tokens(partial) == 7
    assert message_tokens(_ai("x", None)) is None
    assert message_tokens({"role": "assistant", "content": "x"}) is None


def test_usage_tokens_counts_only_current_turn() -> None:
    history = [HumanMessage(content="old"), _ai("old-a", 100), HumanMessage(content="new"), _ai("new-a", 7)]
    assert usage_tokens(history) == 7
    assert usage_tokens([HumanMessage(content="q"), _ai("a", None)]) is None


async def test_complete_with_usage_prefers_provider_count() -> None:
    model = ScriptedModel(script=Script([_ai("hello", 42)]))
    text, tokens = await complete_with_usage(model, "sys", "user")
    assert (text, tokens) == ("hello", 42)


async def test_complete_with_usage_estimates_when_provider_silent() -> None:
    model = ScriptedModel(script=Script([answer("hello there")]))
    text, tokens = await complete_with_usage(model, "sys", "user")
    assert text == "hello there"
    assert tokens > 0
```

Plus a SwarmSDK-level test that `RunResult.tokens` equals the scripted provider total for the router+swarm path when the scripted `AIMessage` carries `usage_metadata` (follow the existing `_sdk(...)` helper pattern in `test_swarm.py` lines ~60-90; assert `result.tokens == 42` for a single-call parallel/swarm answer whose final AI message reports 42 and whose router call is cheap). If the router's tokens are also added the expected value is router + swarm; compute it explicitly in the test rather than guessing.

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest Agents/tests/test_swarm.py -q --tb=short -k "message_tokens or usage_tokens or complete_with_usage"`
Expected: FAIL with `ImportError: cannot import name 'complete_with_usage'`.

- [ ] **Step 3: Implement**

`chat.py`:

```python
from swarm_sdk.prompting.budget import count_text


def message_tokens(message: object) -> int | None:
    """Return the provider-reported token total for one message, if any."""
    meta = message.get("usage_metadata") if isinstance(message, dict) else getattr(message, "usage_metadata", None)
    if not isinstance(meta, dict):
        return None
    total = meta.get("total_tokens")
    if isinstance(total, int):
        return total
    inp, out = meta.get("input_tokens"), meta.get("output_tokens")
    if isinstance(inp, int) and isinstance(out, int):
        return inp + out
    return None


def usage_tokens(messages: list[object]) -> int | None:
    """Sum provider token totals for AI messages after the last human message."""
    start = 0
    for index, message in enumerate(messages):
        kind = message.get("role") or message.get("type") if isinstance(message, dict) else getattr(message, "type", None)
        if kind in {"human", "user"}:
            start = index + 1
    reported = [t for m in messages[start:] if (t := message_tokens(m)) is not None]
    return sum(reported) if reported else None


async def complete_with_usage(
    model: BaseChatModel, system: str, user: str, *, json_mode: bool = False
) -> tuple[str, int]:
    """Invoke ``model`` and return ``(text, tokens)``; tokens are the provider's when reported."""

    def _call() -> tuple[str, int]:
        runnable = model
        if json_mode:
            try:
                runnable = model.bind(response_format={"type": "json_object"})
            except (AttributeError, TypeError, ValueError):
                runnable = model
        result = runnable.invoke([SystemMessage(content=system), HumanMessage(content=user)])
        text = message_text(result)
        reported = message_tokens(result)
        if reported is None:
            reported = count_text(system) + count_text(user) + count_text(text)
        return text, reported

    return await offload(_call)


async def complete(model: BaseChatModel, system: str, user: str) -> str:
    text, _ = await complete_with_usage(model, system, user)
    return text
```

Check for an import cycle first: `prompting.budget` imports only `tokenizers`/`tiktoken`, so importing it from `models.chat` is safe (`fanout.py` already does).

`json_mode` failure handling: `bind()` itself rarely raises; the real failure is the provider rejecting `response_format` at `invoke`. In `_call`, wrap the JSON-mode `invoke` in `try/except Exception` and retry once **without** `response_format`; keep the retry bounded to exactly one extra call and re-raise if the plain call fails. Add `test_json_mode_falls_back_when_provider_rejects` with a `ScriptedModel` subclass whose `_generate` raises `ValueError` when `"response_format"` is in kwargs and returns the scripted message otherwise.

`selection.py`: rename the body of `FallbackChain.complete` to `complete_with_usage(..., *, json_mode=False)` calling `complete_with_usage` from `chat` and returning `(result, tokens)`; add `async def complete(...) -> str` that delegates. Import `complete_with_usage` alongside `complete`.

`fanout.py`: use `complete_with_usage` for each specialist and the synthesis call; total tokens = sum of the three provider counts (drop the `count_text` estimates when the provider reports). Keep `SpecialistResult.tokens` populated from the provider count.

`core/swarm.py`:
- `_route`: use `complete_with_usage` / `self._fallback.complete_with_usage` and return the decision **and** tokens; update `run()` to add the route tokens to the total (`route_tokens + answer_tokens`). Update every `_route` call site (grep `_route(`).
- `_swarm`: `tokens = usage_tokens(messages)`; if `None`, keep the existing estimate `self.budget.count(packed.text) + self.budget.count(answer)`.

- [ ] **Step 4: Run to verify pass**

Run: `uv run --extra dev pytest Agents/tests Agents/benchmark -q --tb=short`
Expected: PASS, including `model_fallback` and `model_delegation` benchmarks, which exercise `FallbackChain` (its `complete()` still returns `str`).

- [ ] **Step 5: Commit**

```bash
uv run --extra dev ruff check src/swarm_sdk/models src/swarm_sdk/execution/fanout.py src/swarm_sdk/core/swarm.py
git add src/swarm_sdk/models/chat.py src/swarm_sdk/models/selection.py src/swarm_sdk/execution/fanout.py src/swarm_sdk/core/swarm.py Agents/tests/test_swarm.py
git commit -m "feat: report provider token usage instead of text-length estimates" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 14: Router structured output with regex fallback

**Files:**
- Modify: `src/swarm_sdk/core/swarm.py` (`_route`), `src/swarm_sdk/models/selection.py` (`FallbackChain.complete_with_usage` already accepts `json_mode` from Task 13)
- Test: `Agents/tests/test_swarm.py`

**Interfaces:**
- Consumes: `complete_with_usage(..., json_mode=)` (Task 13), `Settings.router_structured_output` (Task 7).
- Produces: `_route` passes `json_mode=self.settings.router_structured_output`; parsing keeps the existing regex + `json.loads` + `RouteDecision.model_validate` chain, so any output that parsed before still parses.

- [ ] **Step 1: Write the failing tests** (table-driven over adversarial router outputs; each expects a `RouteDecision`, never an exception)

```python
import pytest

_ROUTER_OUTPUTS = [
    ('{"mode":"parallel","tasks":["a","b"]}', "parallel", ["a", "b"]),
    ('Sure! Here you go: {"mode":"parallel","tasks":["a"]} hope that helps', "parallel", ["a"]),
    ('```json\n{"mode":"swarm","tasks":[]}\n```', "swarm", []),
    ('{"mode":"parallel","tasks":["a"', "swarm", []),
    ("", "swarm", []),
    ("no json at all", "swarm", []),
    ('{"mode":"banana","tasks":[]}', "swarm", []),
    ('{"mode":"parallel","tasks":"not-a-list"}', "swarm", []),
]


@pytest.mark.parametrize(("raw", "mode", "tasks"), _ROUTER_OUTPUTS)
async def test_route_survives_adversarial_router_output(tmp_path, raw, mode, tasks) -> None:
    sdk = _sdk_with_router(tmp_path, raw)  # helper below
    decision, _ = await sdk._route(sdk.budget.pack(system="s", memories=[], turns=["q"]))
    assert (decision.mode, decision.tasks) == (mode, tasks)


_FORMAT_SEEN: list[bool] = []


class _FormatSpyModel(ScriptedModel):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        _FORMAT_SEEN.append("response_format" in kwargs)
        return super()._generate(messages, stop, run_manager, **kwargs)


@pytest.mark.parametrize("structured", [True, False])
async def test_route_requests_json_mode_only_when_enabled(tmp_path, structured: bool) -> None:
    _FORMAT_SEEN.clear()
    model = _FormatSpyModel(script=Script([answer('{"mode":"swarm","tasks":[]}')]))
    sdk = SwarmSDK(
        _settings(tmp_path).model_copy(update={"router_structured_output": structured}),
        router_model=model,
        specialist_model=model,
        embedder=HashEmbedder(32),
        reranker=IdentityReranker(),
        memory=OpenClVecStore(32),
    )
    await sdk._route(sdk.budget.pack(system="s", memories=[], turns=["q"]))
    assert _FORMAT_SEEN == [structured]
```

Write `_sdk_with_router(tmp_path, raw)` next to `_sdk()` in `test_swarm.py`: the same construction as above with `router_model=ScriptedModel(script=Script([answer(raw)]))`. Read the existing `_sdk()` helper (lines ~60-90) and copy its keyword arguments exactly, since it may pass additional fields.

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest Agents/tests/test_swarm.py -q --tb=short -k "route"`
Expected: FAIL (`_route` still returns a bare `RouteDecision` after Task 13's change, or `json_mode` is not passed).

- [ ] **Step 3: Implement** — in `_route`, pass `json_mode=self.settings.router_structured_output` on both the injected-model and fallback-chain paths; leave the parse chain intact. Confirm `RouteDecision(mode="parallel", tasks="not-a-list")` raises `ValidationError` (already caught) so the last table row is safe.

- [ ] **Step 4: Run to verify pass**

Run: `uv run --extra dev pytest Agents/tests/test_swarm.py -q --tb=short`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run --extra dev ruff check src/swarm_sdk/core/swarm.py
git add src/swarm_sdk/core/swarm.py Agents/tests/test_swarm.py
git commit -m "feat: request JSON from the router and keep regex as fallback" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 15: Split `system` / `user` for provider prompt caching

**Files:**
- Modify: `src/swarm_sdk/prompting/budget.py` (`PackedPrompt`), `src/swarm_sdk/core/swarm.py` (`_route`)
- Test: `Agents/tests/test_tokens.py`

**Interfaces:**
- Produces: `PackedPrompt.prefix -> str` (the stable system text) and `PackedPrompt.suffix -> str` (the variable user text). `_route` sends `system=ROUTER_SYSTEM` and `user=packed.user or packed.system` as **separate** arguments so a provider can cache the constant system block.

Precision note: `_route` currently sends `packed.text` (system and user joined) as the *user* message while also sending `ROUTER_SYSTEM` as the system message, so the system prompt is transmitted twice. Sending `packed.user` fixes that duplication and is the actual token saving here. Guard: when `packed.user` is empty (budget too tight), send `packed.system`'s content as before so the model never receives an empty user message.

- [ ] **Step 1: Write the failing tests**

```python
def test_packed_prompt_prefix_suffix() -> None:
    from swarm_sdk.prompting.budget import PackedPrompt

    p = PackedPrompt(system="sys", user="body")
    assert (p.prefix, p.suffix) == ("sys", "body")
    assert p.text == "sys\nbody"


async def test_route_does_not_repeat_the_system_prompt(tmp_path) -> None:
    from swarm_sdk.core.swarm import ROUTER_SYSTEM

    script = Script([answer('{"mode":"swarm","tasks":[]}')])
    sdk = _sdk_with_router_script(tmp_path, script)
    packed = sdk.budget.pack(system=ROUTER_SYSTEM, memories=[], turns=["what is 2+2"])
    await sdk._route(packed)
    assert ROUTER_SYSTEM not in script.seen[0]
    assert "what is 2+2" in script.seen[0]
```

`Script.seen` records the last message content per call (`fakes.py`: `last = messages[-1]`, the human message), so it checks exactly the user turn. Add `_sdk_with_router_script` beside `_sdk_with_router` (Task 14) taking a prebuilt `Script`.

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest Agents/tests/test_tokens.py Agents/tests/test_swarm.py -q --tb=short -k "prefix_suffix or repeat_the_system"`
Expected: FAIL (`AttributeError: 'PackedPrompt' object has no attribute 'prefix'`).

- [ ] **Step 3: Implement** — add to `PackedPrompt`:

```python
    @property
    def prefix(self) -> str:
        """Stable, cache-friendly part of the prompt."""
        return self.system

    @property
    def suffix(self) -> str:
        """Variable part of the prompt (may be empty)."""
        return self.user
```

In `_route`, replace the user argument `packed.text` with `packed.suffix or packed.prefix`.

- [ ] **Step 4: Run to verify pass**

Run: `uv run --extra dev pytest Agents/tests -q --tb=short`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run --extra dev ruff check src/swarm_sdk/prompting/budget.py src/swarm_sdk/core/swarm.py
git add src/swarm_sdk/prompting/budget.py src/swarm_sdk/core/swarm.py Agents/tests/test_tokens.py Agents/tests/test_swarm.py
git commit -m "perf: stop sending the router system prompt twice" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 16: Bound conversation-thread memory (`max_threads`)

**Files:**
- Modify: `src/swarm_sdk/core/swarm.py` (`__init__`, `_swarm`)
- Test: `Agents/tests/test_swarm.py`

**Interfaces:**
- Produces: `SwarmSDK(..., max_threads: int = 200)`. `self._threads` becomes a `dict[str, None]` (insertion-ordered set) guarded by a `threading.Lock`; when a new id would exceed `max_threads`, the oldest `max(1, max_threads // 4)` ids are dropped and each is passed to `InMemorySaver.delete_thread(thread_id)` if the checkpointer exposes it (verify with `hasattr`; skip otherwise).

Verify first: `uv run python -c "from langgraph.checkpoint.memory import InMemorySaver; print(hasattr(InMemorySaver, 'delete_thread'))"`. If it prints `False`, eviction can only drop the SDK's own bookkeeping and the checkpointer's RAM is **not** freed. In that case say so in the commit body and in the plan's follow-ups instead of claiming a RAM win.

- [ ] **Step 1: Write the failing tests**

```python
def test_thread_registry_evicts_oldest(tmp_path) -> None:
    sdk = _sdk(tmp_path, max_threads=8)
    for n in range(20):
        sdk._register_thread(f"t{n}")
    assert len(sdk._threads) <= 8
    assert "t19" in sdk._threads
    assert "t0" not in sdk._threads


def test_thread_registry_reregistering_keeps_thread(tmp_path) -> None:
    sdk = _sdk(tmp_path, max_threads=4)
    for n in range(4):
        sdk._register_thread(f"t{n}")
    sdk._register_thread("t3")
    assert len(sdk._threads) == 4


def test_evicted_thread_can_start_again(tmp_path) -> None:
    sdk = _sdk(tmp_path, max_threads=4)
    for n in range(10):
        sdk._register_thread(f"t{n}")
    assert sdk._register_thread("t0") is True  # treated as a new thread again
```

`_register_thread(thread_id) -> bool` returns `True` when the id was not tracked (the caller then seeds `active_agent="researcher"`, exactly what `_swarm` does today with `thread_id not in self._threads`). Adapt `_sdk` in the test file to accept `max_threads`.

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest Agents/tests/test_swarm.py -q --tb=short -k thread_registry`
Expected: FAIL (`AttributeError: ... '_register_thread'`).

- [ ] **Step 3: Implement**

```python
    def _register_thread(self, thread_id: str) -> bool:
        """Track ``thread_id``; return True if it is new. Evicts the oldest ids past the cap."""
        with self._threads_lock:
            if thread_id in self._threads:
                return False
            self._threads[thread_id] = None
            if len(self._threads) > self.max_threads:
                drop = max(1, self.max_threads // 4)
                for stale in list(self._threads)[:drop]:
                    del self._threads[stale]
                    delete = getattr(self._checkpointer, "delete_thread", None)
                    if callable(delete):
                        delete(stale)
            metrics.set_active_threads(len(self._threads))
            return True
```

Keep the `InMemorySaver()` in `self._checkpointer` (create it in `__init__`, pass it to `workflow.compile(checkpointer=self._checkpointer)`). In `_swarm`, replace the `if thread_id not in self._threads:` block with `if self._register_thread(thread_id): payload["active_agent"] = "researcher"`. Guard the just-registered id: it is appended last so it is never among the dropped oldest ids when `max_threads >= 2`; reject `max_threads < 2` in `__init__` with `ValueError`. Import `threading` and `from swarm_sdk.observability import metrics`.

- [ ] **Step 4: Run to verify pass**

Run: `uv run --extra dev pytest Agents/tests/test_swarm.py -q --tb=short`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run --extra dev ruff check src/swarm_sdk/core/swarm.py
git add src/swarm_sdk/core/swarm.py Agents/tests/test_swarm.py
git commit -m "fix: cap tracked conversation threads" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 17: GPU softmax in the reranker

**Files:**
- Modify: `src/swarm_sdk/retrieval/rerank.py`
- Test: `Agents/tests/test_memory.py` (rerank tests live with retrieval helpers) or a new `Agents/tests/test_rerank.py`

**Interfaces:**
- Consumes: `batch_softmax` (Task 9).
- Produces: `FastEmbedReranker.rerank_scored(query, documents) -> list[tuple[str, float]]` returning `(document, probability)` sorted best-first; `rerank()` keeps returning `list[str]` in the same order as before.

Why a new method: the spec says the reranker should use `batch_softmax`, but `rerank()` returns only an ordering, and softmax is monotonic, so it cannot change that ordering. The probabilities are only useful to a caller that wants a confidence cut-off, so they are exposed through `rerank_scored` and nothing else changes. `SwarmSDK.recall` stays as it is.

- [ ] **Step 1: Write the failing tests** (new `Agents/tests/test_rerank.py`)

```python
"""Reranker ordering and scored output."""

from __future__ import annotations

import pytest

from swarm_sdk.retrieval.rerank import FastEmbedReranker


class _FakeEncoder:
    def rerank(self, query: str, documents: list[str]) -> list[float]:
        del query
        return [float(len(d)) for d in documents]


def _reranker() -> FastEmbedReranker:
    r = FastEmbedReranker()
    r._model = _FakeEncoder()
    return r


def test_rerank_order_unchanged() -> None:
    assert _reranker().rerank("q", ["aa", "a", "aaa"]) == ["aaa", "aa", "a"]


def test_rerank_scored_probabilities_sum_to_one_and_sorted() -> None:
    scored = _reranker().rerank_scored("q", ["aa", "a", "aaa"])
    assert [d for d, _ in scored] == ["aaa", "aa", "a"]
    assert sum(p for _, p in scored) == pytest.approx(1.0, abs=1e-5)


def test_rerank_scored_empty() -> None:
    assert _reranker().rerank_scored("q", []) == []
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest Agents/tests/test_rerank.py -q --tb=short`
Expected: FAIL (`AttributeError: 'FastEmbedReranker' object has no attribute 'rerank_scored'`).

- [ ] **Step 3: Implement**

```python
    def rerank_scored(self, query: str, documents: list[str]) -> list[tuple[str, float]]:
        """Return ``(document, probability)`` best-first; probabilities sum to 1."""
        if not documents:
            return []
        from swarm_sdk.gpu import batch_softmax

        scores = [float(s) for s in self._load().rerank(query, documents)]
        probs = batch_softmax(np.asarray(scores, dtype=np.float32))
        order = sorted(range(len(documents)), key=lambda i: scores[i], reverse=True)
        return [(documents[i], float(probs[i])) for i in order]
```

Add `import numpy as np` at the top. `batch_softmax` is NumPy-only (Task 9), so there is no GPU dispatch to gate.

- [ ] **Step 4: Run to verify pass**

Run: `uv run --extra dev pytest Agents/tests/test_rerank.py Agents/tests/test_memory.py -q --tb=short`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run --extra dev ruff check src/swarm_sdk/retrieval/rerank.py Agents/tests/test_rerank.py
git add src/swarm_sdk/retrieval/rerank.py Agents/tests/test_rerank.py
git commit -m "feat: reranker exposes softmax probabilities" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 18: Wire spans and metrics into `SwarmSDK.run()`

**Files:**
- Modify: `src/swarm_sdk/core/swarm.py`
- Test: `Agents/tests/test_swarm.py`

**Interfaces:**
- Consumes: `metrics.*` (Task 4), `tracing.span` (Task 5), `UsageLog.add(..., latency_ms=, model=)` (Task 3).
- Produces: `run()` records a request counter, per-step latency (`cache_lookup`, `recall`, `route`, `swarm`/`fanout`), cache-hit kind (`exact` vs `semantic`), token usage, and a `UsageLog` row with `latency_ms`. Behavior and return values are unchanged.

Exact vs semantic: `SemanticCache.lookup` returns only the text. Add a `last_hit_kind: str | None` attribute on `SemanticCache` set to `"exact"`/`"semantic"`/`None` at the end of each `lookup` (it is written under the same lock as reads; document that it is only meaningful immediately after the call from the same task). Simpler and race-free: add `SemanticCache.lookup_kind(text) -> tuple[str | None, str | None]` returning `(response, kind)` and make `lookup()` delegate to it. Use that one; do not add shared mutable state.

- [ ] **Step 1: Write the failing tests**

```python
async def test_run_records_usage_latency(tmp_path) -> None:
    sdk = _sdk(tmp_path)
    result = await sdk.run("hello")
    rows = sdk.usage.summary()
    assert rows and rows[0]["latency_ms_total"] > 0.0
    assert result.tokens == sum(int(r["tokens"]) for r in rows)


async def test_run_survives_without_observability_extras(tmp_path) -> None:
    sdk = _sdk(tmp_path)
    assert (await sdk.run("hello")).text


def test_cache_lookup_kind_distinguishes_exact_and_semantic(tmp_path) -> None:
    embedder = SemanticBucketEmbedder()
    cache = SemanticCache(str(tmp_path / "c.db"), embedder, threshold=0.97)
    cache.store("topic one", "ans")
    assert cache.lookup_kind("topic one") == ("ans", "exact")
    assert cache.lookup_kind("topic two") == ("ans", "semantic")
    assert cache.lookup_kind("nothing like it") == (None, None)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest Agents/tests/test_swarm.py -q --tb=short -k "usage_latency or lookup_kind"`
Expected: FAIL (`AttributeError: ... 'lookup_kind'`; `latency_ms_total` is `0.0`).

- [ ] **Step 3: Implement**

`cache.py`: rename the current `lookup` body to `lookup_kind` returning `(response, kind)` (`"exact"` for the hash hit, `"semantic"` for a vector hit, `(None, None)` otherwise) and add `def lookup(self, text) -> str | None: return self.lookup_kind(text)[0]`.

`swarm.py`: import `time`, `metrics`, `tracing`. Wrap `run()`:

```python
        started = time.perf_counter()
        with tracing.span("swarm.run", thread_id_set=bool(thread_id)):
            ...
```

Do **not** put `text` or `thread_id` values in span attributes (may contain user data). Around each step take `t = time.perf_counter()` and `metrics.observe_step(step, time.perf_counter() - t)`. On a cache hit call `metrics.record_cache_hit(kind)` and `metrics.record_request("cache", True)`. On a normal run call `metrics.record_request(mode, False)`, `metrics.record_tokens(agent, model_name, tokens)` and `self.usage.add(agent, tokens, False, latency_ms=elapsed_ms, model=model_name)`, where `model_name` is `self.settings.specialist_model` for `swarm`/`parallel`. Use `await offload(self.cache.lookup_kind, text)` in place of `lookup`.

Because `run()` is `async`, use a plain `with tracing.span(...)` (the span helper is a sync context manager; this is safe across `await` inside one task).

- [ ] **Step 4: Run to verify pass**

Run: `uv run --extra dev pytest Agents/tests Agents/benchmark -q --tb=short` and `uv run --extra dev --extra observability pytest Agents/tests/test_swarm.py -q --tb=short`
Expected: PASS in both.

- [ ] **Step 5: Commit**

```bash
uv run --extra dev ruff check src/swarm_sdk/core/swarm.py src/swarm_sdk/retrieval/cache.py
git add src/swarm_sdk/core/swarm.py src/swarm_sdk/retrieval/cache.py Agents/tests/test_swarm.py
git commit -m "feat: emit spans, metrics and latency from SwarmSDK.run" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 19: Benchmark `gpu_quantization`

**Files:**
- Create: `Agents/benchmark/Tasks/gpu_quantization/benchmark_gpu_quantization.py`, `Agents/benchmark/Tasks/gpu_quantization/test_gpu_quantization.py`

**Interfaces:**
- Consumes: `OpenClVecStore(quantize=...)` (Task 10). Follow `Tasks/gpu_retrieval/benchmark_gpu_retrieval.py` for structure: `run(...) -> dict`, `main()`, `--write-results` to `Agents/benchmark/results/gpu_quantization/`.
- Produces: `run(rows: int, dim: int, queries: int, k: int, seed: int = 7) -> dict[str, object]` with `profiles`: one entry per `(backend in numpy/opencl) x (quantize in none/int8/binary)` holding `p50_ms`, `p95_ms`, `resident_vector_bytes`, `peak_rss_bytes`, `recall_at_k` (vs exact float32 NumPy inner product), plus `best_by_recall` naming the smallest-footprint mode with `recall_at_k >= 0.9`.

- [ ] **Step 1: Write the failing test** (`test_gpu_quantization.py`; small sizes so it runs in CI on the NumPy path)

```python
from __future__ import annotations

from benchmark.Tasks.gpu_quantization.benchmark_gpu_quantization import run


def test_quantization_benchmark_reports_all_modes() -> None:
    report = run(rows=200, dim=64, queries=5, k=5)
    modes = {(p["backend"], p["quantize"]) for p in report["profiles"]}
    assert ("numpy", "none") in modes and ("numpy", "binary") in modes
    none = next(p for p in report["profiles"] if p["backend"] == "numpy" and p["quantize"] == "none")
    binary = next(p for p in report["profiles"] if p["backend"] == "numpy" and p["quantize"] == "binary")
    assert none["recall_at_k"] == 1.0
    assert binary["resident_vector_bytes"] < none["resident_vector_bytes"]
```

Check how the existing benchmark tests import (`sed -n 1,20p Agents/benchmark/Tasks/hybrid_recall/*.py`) and copy that import style; `pyproject` sets `pythonpath = [".", "Agents"]`, so the module path may be `benchmark.Tasks...` or a relative import. Match what works.

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest Agents/benchmark/Tasks/gpu_quantization -q --tb=short`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement** the script by copying the structure of `benchmark_gpu_retrieval.py` (seeded `np.random.default_rng`, the `_percentile`/`_peak_rss_bytes` helpers, the `SWARM_OPENCL_MIN_ROWS=1` override restored in a `finally`). Loop `for backend, enabled in (("numpy", False), ("opencl", True))` and `for mode in ("none","int8","binary")`, build `OpenClVecStore(dim, max_vectors=rows, quantize=mode)`, time queries, and compute recall against `vectors @ query` top-k. Skip the `opencl` backend entry, with `"skipped": "opencl unavailable"`, when `opencl_available()` is false. Add `argparse` flags `--rows`, `--dim`, `--queries`, `--k`, `--write-results`, `--json`.

- [ ] **Step 4: Run to verify pass**

Run: `uv run --extra dev pytest Agents/benchmark/Tasks/gpu_quantization -q --tb=short`
Then on the Mac: `SWARM_OPENCL_DEVICE="AMD Radeon Pro 5300M" uv run --extra dev --extra opencl python Agents/benchmark/Tasks/gpu_quantization/benchmark_gpu_quantization.py --rows 20000 --dim 384 --queries 50 --k 10 --write-results`
Expected: the CI test passes; the Radeon run prints a report. Record the measured p50/p95/recall numbers in the commit body, labelled **measured**. If pyopencl is missing, say the GPU rows were not run.

- [ ] **Step 5: Commit**

```bash
uv run --extra dev ruff check Agents/benchmark/Tasks/gpu_quantization
git add Agents/benchmark/Tasks/gpu_quantization
git commit -m "bench: quantization sweep (none/int8/binary) on OpenClVecStore" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 20: Benchmark `semantic_cache_gpu`

**Files:**
- Create: `Agents/benchmark/Tasks/semantic_cache_gpu/benchmark_semantic_cache_gpu.py`, `Agents/benchmark/Tasks/semantic_cache_gpu/test_semantic_cache_gpu.py`

**Interfaces:**
- Consumes: `SemanticCache(..., use_index=)` (Task 12), `HashEmbedder`.
- Produces: `run(entries: tuple[int, ...] = (1000, 10000), queries: int = 50, dim: int = 64, seed: int = 7) -> dict[str, object]`; for each entry count: `{"entries", "scan_p50_ms", "scan_p95_ms", "index_p50_ms", "index_p95_ms", "parity": bool}` where `parity` is true when both paths return the same answer for every query.

The spec asks for 1k / 10k / 100k. Seeding 100k rows through `store()` (one SQLite commit each) is slow, so batch the seed by inserting rows directly with `executemany` in one transaction inside the benchmark. The 100k size stays available as a CLI value (`--entries 1000 10000 100000`); the default and the CI test use small sizes.

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

from benchmark.Tasks.semantic_cache_gpu.benchmark_semantic_cache_gpu import run


def test_cache_benchmark_paths_agree() -> None:
    report = run(entries=(200,), queries=10, dim=32)
    (row,) = report["results"]
    assert row["parity"] is True
    assert row["entries"] == 200
    assert row["index_p50_ms"] >= 0.0
```

Note on parity: the index holds only the newest 256 rows (Task 12), so at more than 256 entries the two paths can legitimately differ for an old-row semantic match. Make the benchmark generate queries as near-duplicates of the **newest** rows, and report `parity_scope: "newest_256"` alongside the boolean. Do not claim full parity at 10k+.

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest Agents/benchmark/Tasks/semantic_cache_gpu -q --tb=short`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement** the script (seeded RNG, temp SQLite files under `tempfile.TemporaryDirectory`, `time.perf_counter` around `lookup`, `argparse` flags `--entries`, `--queries`, `--dim`, `--write-results`).

- [ ] **Step 4: Run to verify pass**

Run: `uv run --extra dev pytest Agents/benchmark/Tasks/semantic_cache_gpu -q --tb=short`, then `uv run --extra dev python Agents/benchmark/Tasks/semantic_cache_gpu/benchmark_semantic_cache_gpu.py --entries 1000 10000 --write-results` and record the measured numbers.

- [ ] **Step 5: Commit**

```bash
uv run --extra dev ruff check Agents/benchmark/Tasks/semantic_cache_gpu
git add Agents/benchmark/Tasks/semantic_cache_gpu
git commit -m "bench: semantic cache scan vs indexed lookup" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 21: Benchmarks `structured_router` and `token_count_cache`

**Files:**
- Create: `Agents/benchmark/Tasks/structured_router/test_structured_router.py`, `Agents/benchmark/Tasks/token_count_cache/benchmark_token_count_cache.py`, `Agents/benchmark/Tasks/token_count_cache/test_token_count_cache.py`

**Interfaces:**
- `structured_router`: a pytest-only task (like `model_fallback`, which ships `test_*.py` plus `task.yaml`). It replays the 8 adversarial outputs from Task 14 through `_route` with `router_structured_output=True` and `False` and asserts the **parse failure rate is 0** in both, printing a table of `(raw_prefix, mode, tasks)`. "Failure" here means an exception or an unexpected mode; falling back to the default `RouteDecision` for garbage input counts as handled, and is reported separately as `defaulted`.
- `token_count_cache`: `run(turns: int = 50, seed: int = 7) -> dict[str, object]` replays a synthetic multi-turn session (a fixed system prompt plus growing turn list packed with `TokenBudget.pack` each turn) with a counting tokenizer and reports `encode_calls_uncached` (cache cleared before every call) vs `encode_calls_cached`, and `reduction_pct`.

- [ ] **Step 1: Write the failing tests**

```python
# test_token_count_cache.py
from benchmark.Tasks.token_count_cache.benchmark_token_count_cache import run


def test_cache_reduces_encode_calls() -> None:
    report = run(turns=20)
    assert report["encode_calls_cached"] < report["encode_calls_uncached"]
    assert report["reduction_pct"] > 0


# test_structured_router.py
import pytest
from tests.fakes import ROUTER_OUTPUTS, sdk_with_router


@pytest.mark.parametrize("structured", [True, False])
@pytest.mark.parametrize(("raw", "mode", "tasks"), ROUTER_OUTPUTS)
async def test_parse_never_raises(tmp_path, structured, raw, mode, tasks) -> None:
    sdk = sdk_with_router(tmp_path, raw, structured=structured)
    decision, _ = await sdk._route(sdk.budget.pack(system="s", memories=[], turns=["q"]))
    assert (decision.mode, decision.tasks) == (mode, tasks)
```

Move `_ROUTER_OUTPUTS` and `_sdk_with_router` (Task 14) into `Agents/tests/fakes.py` as public `ROUTER_OUTPUTS` and `sdk_with_router(tmp_path, raw, *, structured=True)`, and update `test_swarm.py` to import them. `fakes.py` cannot import `_settings` from `test_swarm.py` (circular), so give `sdk_with_router` its own `Settings(memory_path=..., cache_path=...)` construction copied from `_settings`. This keeps one copy of the table.

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest Agents/benchmark/Tasks/structured_router Agents/benchmark/Tasks/token_count_cache -q --tb=short`
Expected: FAIL (`ModuleNotFoundError` / `ImportError`).

- [ ] **Step 3: Implement** both. `token_count_cache`: wrap a tokenizer class with a call counter; for the uncached leg call `budget._COUNT_CACHE.clear()` before each `count_text`, for the cached leg leave it. Add a `task.yaml` beside each new task mirroring `Agents/benchmark/Tasks/model_fallback/task.yaml` (read it first and copy its keys).

- [ ] **Step 4: Run to verify pass**

Run: `uv run --extra dev pytest Agents/benchmark -q --tb=short`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run --extra dev ruff check Agents/benchmark Agents/tests
git add Agents/benchmark/Tasks/structured_router Agents/benchmark/Tasks/token_count_cache Agents/tests
git commit -m "bench: structured router parsing and token-count cache" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 22: Benchmark README section

**Files:**
- Modify: `Agents/benchmark/README.md` (already has unrelated uncommitted edits; append only)

- [ ] **Step 1:** Run `git diff Agents/benchmark/README.md` to see the existing uncommitted hunks, then append a section titled `## GPU quantization & structured routing` after the last existing section, in the file's style (command block, then one paragraph of what is measured):

```markdown
## GPU quantization & structured routing

Precision/footprint sweep for `OpenClVecStore` (`none` / `int8` / `binary`):

​```bash
SWARM_OPENCL_DEVICE="AMD Radeon Pro 5300M" uv run --extra opencl \
  python Agents/benchmark/Tasks/gpu_quantization/benchmark_gpu_quantization.py --write-results
​```

Reports p50/p95 latency, resident vector bytes, peak RSS and Recall@K against exact float32 inner product.

Semantic-cache lookup, full scan vs the in-memory index:

​```bash
uv run python Agents/benchmark/Tasks/semantic_cache_gpu/benchmark_semantic_cache_gpu.py --entries 1000 10000
​```

The index holds the newest 256 entries, so parity is reported for that window only.

Router parsing and token-count cache (pytest, no API keys):

​```bash
uv run pytest Agents/benchmark/Tasks/structured_router Agents/benchmark/Tasks/token_count_cache -q
​```
```

(Use real triple backticks; the zero-width characters above only keep this plan file's own fences intact. Do not paste them.)

- [ ] **Step 2:** Verify every command in the section runs: execute each one and confirm exit code 0 (the two benchmark scripts may print to stdout only).
- [ ] **Step 3: Commit.** Because the file has pre-existing hunks, use `git add -p Agents/benchmark/README.md` and stage only the new section.

```bash
git commit -m "docs: document quantization, cache and router benchmarks" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 23: Agent contracts (MLSpecialist, Optimizer, DevOps)

**Files:**
- Modify: `Agents/MLSpecialist/AGENTS.md`, `Agents/Optimizer/AGENTS.md`, `Agents/DevOps/AGENTS.md`

Each file has the sections `Responsibilities`, `Behavioral guidelines`, `Output contract` (JSON). Add **one bullet under `Responsibilities`** and **one numbered guideline** to each, and leave the JSON contract untouched so `swarm_sdk.agents.validate` keeps passing.

- MLSpecialist, Responsibilities: `- Choose the vector precision (opencl_quantize: none | int8 | binary) from gpu.report.acceleration_report() and the gpu_quantization benchmark, stating the Recall@K cost`. Guideline 7: `**Quantization is a measured trade.** Pick a mode only with Recall@K, p95 latency and resident bytes from Agents/benchmark/Tasks/gpu_quantization on the target host; default to none.`
- Optimizer, Responsibilities: `- Calibrate the semantic-cache threshold and review UsageLog / Prometheus latency before proposing think-level changes`. Guideline 7: `**Calibrate, do not guess thresholds.** Change semantic_threshold only with precision measured on stored query pairs; adaptive think-level tuning is proposed, not applied, until latency data exists.`
- DevOps, Responsibilities: `- Wire OpenTelemetry/Prometheus exporters and the vectorstore.quantize / router.structured_output keys in swarm.yaml`. Guideline 7: `**Exporters via environment.** Endpoints and keys come from environment variables, never from committed config; install with the observability extra.`

- [ ] **Step 1:** Read each file's current guideline count (`rg -n '^[0-9]+\. ' Agents/<Name>/AGENTS.md`) and number the new guideline to follow the last one (the files above end at 6; verify).
- [ ] **Step 2:** Apply the edits with the Edit tool.
- [ ] **Step 3:** Run `uv run python -m swarm_sdk.agents.validate` and `uv run --extra dev pytest Agents/tests -q --tb=short`. Expected: PASS.
- [ ] **Step 4: Commit**

```bash
git add Agents/MLSpecialist/AGENTS.md Agents/Optimizer/AGENTS.md Agents/DevOps/AGENTS.md
git commit -m "docs: extend MLSpecialist, Optimizer and DevOps contracts" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 24: Full gate and README

**Files:**
- Modify: `README.md` (already has unrelated uncommitted edits; use `git add -p`)

- [ ] **Step 1:** Add a short README section documenting the new knobs: `SWARM_OPENCL_QUANTIZE`, `SWARM_SEMANTIC_CACHE_ON_GPU`, `SWARM_CACHE_TTL_DAYS`, `SWARM_ROUTER_STRUCTURED_OUTPUT`, the `observability` extra (`uv sync --extra observability`) and the `vectorstore.quantize` / `router.structured_output` YAML keys, each with its default. Follow the AGENTS.md rule to update `README.md` when install steps or behavior change. Confirm the env var names by running `uv run python -c "from swarm_sdk.config.settings import Settings; print(Settings.model_fields.keys())"` (pydantic-settings prefix is `SWARM_`).
- [ ] **Step 2:** Run the full gate:

```bash
uv run --extra dev pytest Agents/tests Agents/benchmark -q --tb=short
uv run --extra dev ruff check src Agents/tests Agents/benchmark Main
uv run --extra dev ty check src Agents/tests Agents/benchmark Main
uv run python -m swarm_sdk.agents.validate
```

Expected: all green. If `ty` reports errors, fix the code, not the config. Report the exact tail of each command's output.
- [ ] **Step 3:** Run the Radeon smoke: `SWARM_OPENCL_DEVICE="AMD Radeon Pro 5300M" uv run --extra dev --extra opencl python -m swarm_sdk.gpu.report` and confirm `opencl_compute: True`. If OpenCL is unavailable, say the GPU path was not exercised.
- [ ] **Step 4: Commit**

```bash
git add -p README.md
git commit -m "docs: document new optimization settings" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

## Self-review

**Spec coverage**

| Spec section | Task(s) |
| --- | --- |
| 1 Observability (metrics, tracing, UsageLog) | 3, 4, 5, 18 |
| 2 Token accuracy, LRU count cache | 1, 13 |
| 3 RAM: SemanticCache index, WAL, thread cap | 6, 12, 16 |
| 4 Import hygiene | 2 (scoped down, see Deviations) |
| 5 GPU kernels, OpenClVecStore modes, reranker, router JSON, prefix/suffix, settings, yaml | 8, 9, 10, 11, 14, 15, 17 |
| Cache TTL (`cache_ttl_days`) | 7 |
| 6 Benchmarks + README | 19, 20, 21, 22 |
| 7 Agent contracts | 23 |
| Testing / gate / rollout | 24 |

Known narrowings versus the spec, all listed under "Deviations": `complete()` stays `str`; embedder imports were already lazy; `binary_quantize`/`batch_softmax`/`quantize_int8` have no GPU dispatch (NumPy only) pending measurement in Task 19; `SqliteVecStore` TTL is out of scope; `pyopencl` import-time initialization is untouched.

**Placeholder scan:** the code steps contain real code. Three helpers are described rather than pasted, each with its exact contract: `_run_row_kernel` / `_run_int8_kernel` / `_run_binary_kernel` (Task 8/9, mirror `batch_dot`'s buffer handling), the `OpenClVecStore` per-mode array plumbing (Task 10) and the benchmark scripts (Tasks 19-21, mirror `benchmark_gpu_retrieval.py`). An implementer must read the named model file for each; that is deliberate, to avoid duplicating 60+ lines of buffer boilerplate here.

**Type consistency:** `complete_with_usage -> tuple[str, int]` (13) is consumed by `_route` (14, 15), `fan_out` (13) and `FallbackChain` (13). `_route` returns `(RouteDecision, int)` after Task 13, and Tasks 14/15/18 assume that shape. `lookup_kind -> tuple[str | None, str | None]` (18) sits on top of `SemanticCache` from Tasks 7 and 12. `binary_dot(bits, query_bits, *, dim)` (9) is called with `dim=self.dim` in Task 10. `Settings.opencl_quantize` (7) feeds `open_store` (11).

**Review Focus coverage:** items 1-2 → Task 1; 3 → Task 13; 4 → Task 14; 5 → Tasks 7, 12; 6 → Tasks 8, 9; 7 → Task 10; 8 → Task 16 (registry lock and re-registration tests; an in-flight run for an evicted id simply gets `active_agent="researcher"` re-seeded on its next call, and LangGraph handles a missing checkpoint as a fresh thread).
