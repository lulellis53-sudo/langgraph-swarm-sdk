# Design Specification: Low-Resource Autonomous Code Synthesis Swarm (`low-swarm`)

> **Document**: `docs/superpowers/specs/2026-10-02-low-resource-swarm-design.md`  
> **Date**: 2026-10-02  
> **Status**: Approved Design (Ready for Implementation Planning)  
> **Target Environment**: macOS 26.7 (Darwin x86_64), MacBookPro16,1 (Intel Core i7-9750H 6c/12t AVX2, 16 GB RAM, AMD Radeon Pro 5300M 4GB VRAM)  
> **Python Runtime**: Python 3.15 / 3.14 (`~/.local/opt/python-3.15-g6413901`)  

---

## 1. Executive Summary & Design Goals

The **`low-swarm`** system is a lightweight, low-resource autonomous code synthesis, refactoring, and verification engine designed specifically for local resource-constrained workstations. Rather than relying on heavyweight, multi-second autoregressive LLM supervisors and uncontrolled background process proliferation, `low-swarm` combines:

1. **Jev AI System-1 Routing**: Sub-35ms non-autoregressive decision tables for safety gating (`Noul`), model tiering (`Score`), and delegation (`Choice`).
2. **Meta Lifeguard AST Pre-Flight Auditing**: Strict static analysis verifying PEP 810 lazy import compliance and blocking prohibited top-level side effects before code execution.
3. **Hardware-Calibrated Concurrency & Memory Ceiling**: Bounded execution strictly obeying the host profile (6 cores / 12 threads, max 2–3 active subagents, 13.6 GB RSS memory ceiling).
4. **macOS Vault Integration**: Zero plaintext secrets, retrieving API keys directly from the macOS Keychain Secure Enclave.
5. **Dual-Mode Vector Acceleration**: PEP 810 lazy-loaded PyOpenCL GPU acceleration across the AMD Radeon Pro 5300M (4GB VRAM) with zero-crash AVX2 CPU SIMD fallback.
6. **RAG Ingestion for Grounded Calibration**: FAISS IVF-PQ vector indexing (98.9% compression) ingesting `~/Documentos/*.md` and `/Users/usuario/Swarm/Agents` to ground the Coder agent and eliminate hallucinations.

---

## 2. System Architecture & Topology

```
+========================================================================================================================+
|                                    LOW-SWARM HIGH-LEVEL RUNTIME ARCHITECTURE                                           |
+========================================================================================================================+

                                            +---------------------------+
                                            |   USER CLI TASK / PROMPT  |
                                            +---------------------------+
                                                          |
                                                          v
                                            +---------------------------+
                                            | RULE ENGINE AUTO-LOADER   |
                                            | Reads ~/AGENTS.md &       |
                                            | /Swarm/Agents/coordination|
                                            +---------------------------+
                                                          |
                                                          v
                                            +---------------------------+
                                            | VAULT KEY MANAGER         |
                                            | Queries macOS Keychain    |
                                            | for OPENAI_API_KEY        |
                                            +---------------------------+
                                                          |
                                                          v
                                            +---------------------------+
                                            | 1. JEV ROUTER NODE        |
                                            | Non-autoregressive <35ms  |
                                            | • Noul: Safety pre-flight |
                                            | • Score: Complexity Tier  |
                                            | • Choice: Agent Target    |
                                            +---------------------------+
                                                          |
                                                          v
                                            +---------------------------+
                                            | 2. CODER SYNTHESIS NODE   |
                                            | Contextual RAG Grounded   |
                                            | Synthesizes Code / Diff   |
                                            +---------------------------+
                                                          |
                                                          v
                                            +---------------------------+
                                            | 3. LIFEGUARD AST AUDITOR  |
                                            | Meta AST Pre-Flight Check |
                                            | • Enforces PEP 810 Lazy   |
                                            | • Blocks Top-Level Syscalls|
                                            +---------------------------+
                                              /                       \
                                    [PASS]   /                         \  [FAIL: Re-synthesize]
                                            v                           v
                              +---------------------------+       +-------------------+
                              | 4. TEST VALIDATOR NODE    |       | RETURN TO CODER   |
                              | Sandboxed Pytest / Syntax |       | (With AST report) |
                              +---------------------------+       +-------------------+
                                            |
                                            v
                              +---------------------------+
                              |   RICH TERMINAL OUTPUT    |
                              | • Git Diff View           |
                              | • Tachyon Profile Report  |
                              | • RSS Memory Delta        |
                              +---------------------------+
```

---

## 3. The Four Core Architectural Pillars

### 3.1 Pillar 1: GPU Acceleration with PEP 810 Lazy Imports
- **Hardware Profile**: AMD Radeon Pro 5300M (Navi 14 architecture, 1,408 compute units, 4GB GDDR6 VRAM).
- **Lazy Loading**: PyOpenCL and Metal/MoltenVK modules are wrapped in PEP 810 lazy imports (`lazy import pyopencl as cl`). The GPU runtime is not initialized during CLI startup, saving 300MB–800MB RSS.
- **Dual-Mode Dispatcher**:
  - For batch similarity matrices $> 1,000$ items, vectors are offloaded to an OpenCL kernel.
  - If GPU memory is saturated (>3.4 GB allocated) or batch size is small, the dispatcher falls back to the host native C++ AVX2 FMA dot-product kernel (`compute_vector_dot_product_avx2`).

### 3.2 Pillar 2: macOS Vault / Keychain Secret Management
- **Security Invariant**: No API keys stored in `.env`, config files, shell history, or process arguments.
- **API**: Uses macOS Keychain Services via `/usr/bin/security`:
  - Query: `security find-generic-password -a "$USER" -s "low-swarm" -w`
  - Store: `security add-generic-password -a "$USER" -s "low-swarm" -w "<secret>" -U`
- Keys are retrieved transiently into Python memory only when the Jev System-1 or LLM synthesis node initializes.

### 3.3 Pillar 3: Grounded RAG Ingestion for Swarm Calibration
- **Knowledge Sources**:
  - `~/Documentos/LangGraphSwarm.MD`
  - `~/Documentos/RAGTECHNIQUES.MD`
  - `~/Documentos/LowResourceOptimization.md`
  - `~/Documentos/toolchain.md`
  - `/Users/usuario/Swarm/Agents/**/*.md`
- **Indexing Engine**: FAISS `IndexIVFPQ` ($M=64, K^*=256$) achieving 98.9% memory compression (64 bytes per 1536-dim vector).
- **Query Interception**: RedisVL / VSS two-tier semantic cache (exact SHA-256 + cosine distance $\le 0.12$) to intercept redundant agent queries in 3–8ms.

### 3.4 Pillar 4: RuleEngine & Dynamic Enforcement of `AGENTS.md`
- **Rule Parser**: Automatically scans and parses `/Users/usuario/AGENTS.md` and `/Users/usuario/Swarm/Agents/coordination.yaml`.
- **Enforced Invariants**:
  - Host CPU: Intel Core i7-9750H (AVX2 only; **strictly prohibit AVX-512**).
  - Modern CLI Tool Preference: Enforce `rg`, `bat`, `fd`, `sd`, `choose`, `eza`. Prohibit raw `grep`, `cat`, `sed`, `awk` in generated shell scripts.
  - Concurrency Limits: Enforce a hard cap of max 2–3 active concurrent subagents.
  - Execution Discipline: Zero-polling reactive execution; background compilation redirected to logs.

---

## 4. Component Specifications & Interfaces

### 4.1 State Schema (`SwarmState`)

```python
from typing import TypedDict, List, Dict, Any, Optional

class SwarmState(TypedDict):
    task: str
    target_files: List[str]
    context_chunks: List[str]
    jev_decision: Dict[str, Any]      # Noul (bool), Score (0.0-1.0), Choice (str)
    synthesized_code: Dict[str, str]  # filepath -> code content
    diff_patches: List[str]
    lifeguard_report: Dict[str, Any]  # status (APPROVED/BLOCKED), violations
    test_results: Dict[str, Any]      # passed (bool), stdout, stderr
    iteration: int                    # Circuit breaker counter (max 3)
    metrics: Dict[str, float]         # peak_rss_mb, elapsed_ms, cpu_percent
```

### 4.2 Jev System-1 Non-Autoregressive Decision Engine
- **`NoulDecision`**: Fast binary assertion verifying task safety and sandbox compliance.
- **`ScoreDecision`**: Computes complexity score $\in [0.0, 1.0]$.
  - $[0.0, 0.4] \implies \text{flash\_lite}$
  - $[0.4, 0.75] \implies \text{flash}$
  - $[0.75, 1.0] \implies \text{pro}$
- **`ChoiceDecision`**: Selects execution route (`coder`, `refactor`, `reviewer`, `tester`).

### 4.3 Meta Lifeguard AST Auditor (`MetaLifeguardAuditor`)
- Implements `ast.NodeVisitor` to inspect synthesized Python code before writing to disk:
  - **Prohibited AST Nodes**: Top-level `os.system`, `subprocess.run`, `eval`, `exec`, `socket`, `open(..., 'w')`.
  - **PEP 810 Validation**: Verifies that third-party module imports are structured for lazy loading.
  - **Rejection Loop**: If violations are found, the node populates `lifeguard_report['violations']` and routes back to the Coder node with the exact AST lint error.

### 4.4 Operational Watchdog & Host Resource Guards
- **Memory RSS Monitor**: Reads process RSS via `psutil` or Darwin `mach_task_basic_info`.
- **Ceiling Invariant**: If host memory exceeds 13.6 GB (85% of 16 GB), the watchdog triggers an emergency semantic cache flush and halts additional agent spawning.

---

## 5. CLI Interface & User Experience

```bash
# General CLI Command Structure
low-swarm [COMMAND] [OPTIONS]

# 1. Run an autonomous synthesis/refactor task
low-swarm run "Add zero-copy memoryview parsing to src/parser.py" \
    --files src/parser.py \
    --tier auto \
    --profile \
    --verbose

# 2. Vault credential management (macOS Keychain)
low-swarm vault set --service openai --key sk-...
low-swarm vault status

# 3. Knowledge base ingestion
low-swarm ingest --source ~/Documentos --output ~/.cache/low-swarm/faiss.idx

# 4. Host diagnostic & rule inspection
low-swarm doctor
```

### Terminal Output (Rich TUI)
- Real-time animated spinner for active node.
- Live telemetry panel showing:
  - Active Node: `[JevRouter] -> [CoderNode] -> [LifeguardAST] -> [TestValidator]`
  - Host RAM: `342 MB / 16,384 MB (Peak: 485 MB)`
  - Decision Latency: `28.4 ms (Jev System-1)`
  - Syntax & AST Status: `APPROVED (PEP 810 compliant)`
- Interactive syntax-highlighted diff display for human review before git staging.

---

## 6. Verification & Testing Strategy

1. **Unit Testing**:
   - `test_vault.py`: Verify macOS Keychain set/get/delete cycles with mock and live backends.
   - `test_jev_router.py`: Verify sub-35ms routing latency and correct `ScoreDecision` bucketing.
   - `test_lifeguard_ast.py`: Assert that unsafe top-level system calls trigger `BLOCKED` status.
   - `test_gpu_dispatcher.py`: Verify automatic CPU AVX2 fallback when PyOpenCL context is mocked as unavailable.
2. **Integration Testing**:
   - End-to-end execution of a code synthesis task against a dummy Python module in a temporary directory.
   - Verify that all generated code passes `ast.parse` and pytest execution.
3. **Performance Profiling**:
   - Profile the runner using Python 3.15 Tachyon sampling profiler (`profiling.sampling`) to confirm $<1.0\%$ profiling overhead.
   - Measure cold-start RSS to ensure baseline footprint remains $<40\text{ MB}$.

---

## 7. Spec Self-Review Checklist

- [x] **Placeholder Scan**: Zero "TBD", "TODO", or unstated requirements.
- [x] **Internal Consistency**: Topology matches the 4 nodes and 4 pillars.
- [x] **Scope Check**: Bounded to a cohesive CLI tool and LangGraph micro-swarm without unnecessary distributed cluster bloat.
- [x] **Ambiguity Check**: Precise definitions for memory ceilings, API key storage, GPU fallback, and AST rules.
