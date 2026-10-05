# Agent Methods: DARS, ReAct, Reflection, SWE, and Codefunction Mappings (2026 Edition)

> Practical, empirical methods for defining high-performance agent workflows, supported by 2026 arXiv multi-agent benchmarks, zero-copy data pipelines, and GIL-free free-threaded execution.

---

## 1. 2026 Empirical Research & Benchmark Foundation

Recent empirical research highlights key trade-offs in multi-agent swarm orchestration:

- **arXiv:2604.02460v1 (Tran & Kiela, 2026 - Stanford)**: *Single-Agent LLMs Outperform Multi-Agent Systems on Multi-Hop Reasoning Under Equal Thinking Token Budgets*. Demonstrates that unguided multi-agent exploration leads to information drift and context bloat unless strictly bounded by distribution-aware depth routing (DARS) and state pruning.
- **arXiv:2601.14652 (Ke et al., 2026)**: *MAS-Orchestra: Holistic Orchestration and Controlled Benchmarks*. Proves that dynamic router control reduces token consumption by > 35% compared to naive full-history handoffs.
- **PEP 703 CPython 3.15 Free-Threading Scaling**: Free-threaded (GIL-less) execution achieves linear throughput scaling up to 32 worker threads when global coarse locks (`threading.Lock()`) are replaced by Reader-Writer locks and atomic counters.

---

## 2. Core Agent Methods Overview

1. **DARS (Distribution-Aware Routing Strategy)**: Routes work by risk, impact, and complexity level (L1 to L4).
2. **ReAct (Reasoning + Acting)**: Alternates between observation, hypothesis, tool action, and verification.
3. **Reflection**: Diagnoses check failures, updates execution hypotheses, and prevents retrying identical broken actions.
4. **SWE (Software Engineering Pipeline)**: Manages end-to-end task lifecycle from requirements analysis through verified quality-gate handoff.

---

## 3. DARS Routing Levels & Execution Thresholds

| Route | Complexity & Signals | Target Subagent | Investigation & Verification Strategy |
| :--- | :--- | :--- | :--- |
| **L1: Bounded** | Local change, single function, zero API impact | `@coder`, `@documenter` | Read local file, apply focused fix, run direct syntax/unit check. |
| **L2: Multi-step** | 2-5 files, internal refactoring, unit tests | `@refactor`, `@tester` | Map callers and interfaces; verify normal, boundary, and error paths. |
| **L3: High-impact** | Security, public API, GIL-free concurrency, memory | `@compilator`, `@security`, `@optimizer` | Source-to-effect reachability trace; run full quality gate (`pytest`, `ruff`, `ty`). |
| **L4: Blocked** | Contradictory requirements or missing credentials | `@planner`, `@orchestrator` | Isolate missing decision/evidence; report clear blocker payload. |

---

## 4. Codefunction Optimization & Architectural Suggestion Matrix

The following matrix maps each core Agent Method directly to code functions in `/Users/usuario/Swarm/src/swarm_sdk/`:

| Core Module File | Code Function | Method Mapping | Current Limitation | 2026 Optimization & Suggestion |
| :--- | :--- | :--- | :--- | :--- |
| **`low_swarm.py`** | `node_jev_router()` | **DARS / ReAct** | Memory check inline; un-pruned context history | Apply `@memory_guarded` decorator; prune state history before complexity scoring (arXiv:2604.02460). |
| **`low_swarm.py`** | `node_coder()` | **SWE** | Duplicated try/except memory guard; string format templates | Use `@memory_guarded` decorator and `orjson` byte serialization for state handoffs. |
| **`low_swarm.py`** | `node_lifeguard()` | **Reflection** | Sequential AST inspection across files | Parallelize AST auditing across 32 GIL-free worker threads via `ThreadPoolExecutor`. |
| **`calcs.py`** | `column_stats()` | **Optimizer** | Local `import pyarrow`; `pa.array()` copies memory | Use module-level `_pa_modules()` cache and `__arrow_c_array__` zero-copy C-Data interface. |
| **`calcs.py`** | `vector_dot()` | **Optimizer** | Re-allocates PyArrow float64 arrays | Verify contiguous buffer memoryviews; compute inner product on zero-copy views. |
| **`opencl_store.py`** | `resident_bytes` | **Memory** | Coarse `threading.Lock()` causes thread contention | Replace with `threading.RLock()` or atomic byte counter `self._resident_bytes_counter`. |
| **`opencl_store.py`** | `search()` | **Memory / RAG** | Global write lock held during KNN GPU/NumPy search | Adopt Reader-Writer lock (allow concurrent `search()` reads; lock exclusively for memory growth). |
| **`vault.py`** | `run_cli()` | **Security** | Unparenthesized exception tuple syntax | Standardize syntax: `except (OSError, subprocess.TimeoutExpired):`. |
| **`allocator.py`** | `get_rss_bytes()` | **Telemetry** | Un-cached CTypes system call per lookup | Cache system call handle with 50ms cooldown timer to reduce sys call overhead. |
| **`swarm.py`** | `dispatch_task()` | **Orchestrator** | Synchronous sequential task queue processing | Dispatch tasks asynchronously via Redis Streams (`XADD`) with consumer groups (`XREADGROUP`). |

---

## 5. Standard CLI Command Handlers

### Run Swarm Task with Specified Agent & Method
```bash
python3 .agents/skills/swarm/scripts/langgraph_swarm.py @compilator --Task "Optimize calcs.py zero-copy Arrow memory buffers" --Effort HIGH --MaxMS 30000 --MaxTry 3
```

### Run Benchmark Telemetry Suite
```bash
python3 .agents/skills/swarm/scripts/benchmark_swarm.py --suite code-quality --iterations 5
```

### Quality Gate Check
```bash
uv run ruff check /Users/usuario/Swarm/src/swarm_sdk/
```
