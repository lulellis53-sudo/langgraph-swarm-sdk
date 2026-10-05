# Lifeguard: Static Safety, Runtime Guards & Operational Self-Healing

> **Scope:** How “Lifeguard” appears in the LangGraph Swarm SDK and adjacent tooling.  
> **Authority:** [`src/swarm_sdk/core/lifeguard_ast.py`](../src/swarm_sdk/core/lifeguard_ast.py), [`low_swarm.py`](../src/swarm_sdk/orchestrator/low_swarm.py), tests in [`tests/test_e2e_benchmark.py`](../tests/test_e2e_benchmark.py).  
> **Extended manual:** [LangSwarm.md §16](LangSwarm.md#16-automated-self-healing--pre-flight-verification-with-lifeguard), [Python3.15.md](Python3.15.md) (PEP 810 lazy imports).

---

## Executive summary

**Lifeguard** is not a single binary in this repo. Swarm uses the name at three layers:

| Layer | What it is | Swarm default |
| :--- | :--- | :--- |
| **A. Meta Lifeguard (upstream)** | Rust/Python static analyzer for **PEP 810 lazy-import** safety ([facebook/Lifeguard](https://github.com/facebook/Lifeguard)) | Optional CLI (`lifeguard_lazy_imports` / `lifeguard` on PyPI); not required to `uv sync` |
| **B. `MetaLifeguardAuditor` (in-repo)** | Python AST gate: **no dangerous import-time calls**, optional **heavy-module lazy-import** hints | **On** in `LowSwarmEngine` `lifeguard_node`; exported from `swarm_sdk.core` |
| **C. LifeguardSystem (upstream)** | YAML-scheduled **validations + remediation actions** ([LifeguardSystem/lifeguard](https://github.com/LifeguardSystem/lifeguard)) | Optional ops daemon; polls like `/healthz` in production layouts |
| **D. Runtime “Lifeguard” hooks** | RSS **memory ceiling** in `AllocatorManager`; **`GET /healthz`** on `swarm-api` | Active when serving or using allocator context managers |

The older one-page “cgroups-only supervisor” description was a generic pattern sketch. On **macOS** (typical dev host), use **launchd**, process limits, and in-process guards (B + D). On **Linux** deploys, combine B/D with **systemd**, **cgroup v2** memory limits, and optionally C.

---

## Decision workflow

```text
                    [Code / agent output]
                              |
              +---------------+---------------+
              |                               |
      [Pre-flight AST]                  [Runtime serve]
   MetaLifeguardAuditor                  swarm-api / graph
   (prohibited calls,                    + AllocatorManager
    optional lazy imports)                 + /healthz
              |                               |
              v                               v
      [Reject -> coder loop]          [MemoryError on ceiling]
              |                               |
              +---------------+---------------+
                              |
                    [Optional ops plane]
              LifeguardSystem validations
              (schedule, execute, actions)
```

---

## Swarm SDK implementation map

| Component | Location | Behavior |
| :--- | :--- | :--- |
| `MetaLifeguardAuditor`, `audit_code` | `core/lifeguard_ast.py` | AST visit; `LifeguardAuditReport.is_approved` |
| Violation categories | same | `prohibited_call`, `unlazy_import`, `syntax_error` |
| Heavy import set | `HEAVY_MODULES` | `torch`, `transformers`, `pandas`, `polars`, `scipy`, `sklearn` |
| Prohibited calls | `EXACT_PROHIBITED_CALLS`, prefixes | `os.system`, `eval`/`exec`, `subprocess.*`, `socket.*`, `shutil.rmtree`, … |
| Graph node | `orchestrator/low_swarm.py` | `node_lifeguard` → handoff back to `coder` on failure (bounded depth) |
| Lazy import proxy | `core/compression.py` | PEP 810–friendly deferred imports for heavy stacks |
| Memory ceiling | `core/allocator.py` | Raises `MemoryError` when RSS ≥ configured GB ceiling |
| Liveness | `serving/http.py` | `GET /healthz` → `{"status":"ok"}` |
| CLI surfacing | `cli.py` | Rich table row **Lifeguard Audit** from `lifeguard_report` state |
| E2E contract | `tests/test_e2e_benchmark.py` | `is_approved=True`, no prohibited calls after `low-swarm run` |

---

## Layer A — Meta Lifeguard (lazy imports, upstream)

From [facebook/Lifeguard](https://github.com/facebook/Lifeguard) (verified via project README, 2026-10-05):

- **Goal:** Find modules that are **unsafe under PEP 810 lazy imports** (deferred load until first use).
- **Method:** Parallel AST analysis; **conservative** — if safety cannot be proved, the module is marked incompatible (`LOAD_IMPORTS_EAGERLY` and related diagnostics).
- **Typical incompatibilities:** module-level side effects, registry-at-import patterns, `sys.modules` manipulation, `exec()`, custom `__del__` timing assumptions.
- **Install / run:** PyPI package `lifeguard_lazy_imports`; CLI `lifeguard` (may lag `main`; use `lifeguard --help`). For explicit lazy syntax, discovery/analysis may need `--python-version 3.15`.

**Relation to Swarm:** `MetaLifeguardAuditor` is inspired by the same *ideas* (lazy + safe imports) but implements a **narrower, security-focused** rule set in pure Python AST — it does **not** replace the Rust Meta Lifeguard CLI for full-repo PEP 810 migration.

---

## Layer B — `MetaLifeguardAuditor` (in-repo)

### API

```python
from swarm_sdk.core.lifeguard_ast import MetaLifeguardAuditor, audit_code

report = audit_code(source, enforce_lazy=False)  # or MetaLifeguardAuditor.audit_code(...)
assert report.is_approved
```

- `enforce_lazy=True` — flag top-level imports of `HEAVY_MODULES` unless suppressed via `# lifeguard` / `# noqa` style markers (see `_has_suppression_comment` in source).
- Module-scope **calls** to prohibited APIs are always violations.

### Low-swarm integration

After the coder produces patches, `lifeguard_node` audits synthesized code. Failures append human-readable feedback and may route back to `coder` (max handoff depth 2). State key: `lifeguard_report` (dict serialized from `LifeguardAuditReport`).

---

## Layer C — LifeguardSystem (operational self-healing)

[LifeguardSystem/lifeguard](https://github.com/LifeguardSystem/lifeguard) describes an **opinionated self-healing** framework:

- **Validations** run on a **schedule** (`every: minutes: N`).
- Each validation **`execute`s** a Python callable (`command: path.to.module.function` + `args`).
- **Actions** are plain functions `(validation_response, settings) -> ...` registered in YAML (e.g. persist results, notify).

Example shape (from upstream docs):

```yaml
validations:
  - validation_name: swarm_api_health
    description: Poll swarm-api liveness
    schedule:
      every:
        minutes: 1
    execute:
      command: mypkg.checks.healthz
      args:
        - "http://127.0.0.1:8080/healthz"
    actions:
      - lifeguard.actions.database.save_result_into_database
```

**Swarm fit:** Point validations at `swarm-api` `/healthz`, Redis when enabled, and LangGraph Server URL; remediation actions remain deployment-specific. Full narrative and sample daemon launch: [LangSwarm.md §16.2–16.3](LangSwarm.md#162-operational-self-healing-daemon-with-lifeguardsystem).

---

## Layer D — Runtime guards (memory & probes)

### Allocator RSS ceiling

`AllocatorManager` tracks RSS during a scoped run. If final RSS exceeds `ceiling_gb`, it sets `report.breached` and raises:

`MemoryError: Lifeguard memory ceiling breached during execution: …`

Use this on **16 GB** dev machines to fail fast before macOS swap thrash (see host profile in root `AGENTS.md`).

### HTTP liveness

`swarm-api` exposes **`GET /healthz`** for load balancers and external supervisors (including LifeguardSystem-style polls). Hardening spec: `docs/superpowers/plans/2026-10-02-langgraph-swarm-hardening.md`.

### Host supervision patterns (not shipped in-repo)

| Signal | Linux (typical) | macOS (dev) |
| :--- | :--- | :--- |
| Memory cap | cgroup v2 `memory.max` | `ulimit -v`, allocator ceiling (D) |
| Restart policy | systemd `Restart=on-failure` | launchd `KeepAlive` |
| Leak trend | `dRSS/dt` from `/proc/pid/statm` | `ps` / Instruments / allocator reports |
| Deadlock / hang | heartbeat + watchdog | same + kill stuck worker |

Do not treat vendor-style “vs systemd” latency tables as Swarm benchmarks unless reproduced in `Agents/benchmark/` with a linked artifact.

---

## Operational checklist

1. **CI / local synthesis:** E2E tests expect `lifeguard_report.is_approved` after `uv run low-swarm run …`.
2. **Lazy-import migration (3.15):** Run upstream `lifeguard` on packages you plan to run with PEP 810; fix `LOAD_IMPORTS_EAGERLY` findings before enabling lazy imports globally.
3. **Serving:** Monitor `/healthz`; configure LifeguardSystem or systemd restarts for the API process.
4. **Memory:** Set allocator ceilings for batch ingest / benchmark jobs on 16 GB hosts.
5. **Docs drill-down:** [LangSwarm.md Part 0](LangSwarm.md#part-0-acceleration-research-synthesis-merged-langgraph_swarm_acceleration_researchmd) (reliability stack), §16 (Meta + LifeguardSystem examples).

---

## Edge cases & pitfalls

| Pitfall | Mitigation |
| :--- | :--- |
| False deadlock from CPU-bound work without heartbeat | Async yields; longer TTL; don’t use heartbeat alone on pure compute |
| Meta Lifeguard vs in-repo auditor mismatch | Use **Rust Meta Lifeguard** for PEP 810 migration; **MetaLifeguardAuditor** for agent codegen safety |
| `enforce_lazy=True` in tests importing torch at module level | Move imports into functions or add documented suppression comments |
| LifeguardSystem action failures | Log `validation_response`; idempotent actions; alert on repeated PROBLEM status |
| Supervisor crash | systemd/`KeepAlive` on API + external monitor — no hypervisor in SDK |

---

## Primary citations & evidence ledger

1. **Meta Lifeguard (lazy imports):** https://github.com/facebook/Lifeguard — AST analyzer; PEP 810 adoption; PyPI `lifeguard_lazy_imports`.
2. **PEP 810 — Lazy imports:** https://peps.python.org/pep-0810/ (syntax and semantics; verify against your Python build).
3. **LifeguardSystem:** https://github.com/LifeguardSystem/lifeguard — scheduled validations, execute hooks, action functions.
4. **cgroup v2 memory:** https://www.kernel.org/doc/Documentation/cgroup-v2.txt — optional Linux memory limits.
5. **Swarm implementation:** `src/swarm_sdk/core/lifeguard_ast.py`, `src/swarm_sdk/orchestrator/low_swarm.py`.
6. **Personal host copy (optional):** `~/Documentos/Lifeguard.md` — sync with this file when changing Lifeguard narrative repo-wide.
