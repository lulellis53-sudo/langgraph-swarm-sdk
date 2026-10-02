# Low-Resource Autonomous Code Synthesis Swarm (`low-swarm`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a production-grade, low-resource autonomous code synthesis and refactoring CLI system (`low-swarm`) running on Python 3.15 / 3.14 that integrates Jev AI System-1 routing (<35ms), Meta Lifeguard AST auditing, macOS Keychain Vault secrets, PEP 810 lazy-loaded GPU acceleration (AMD Radeon Pro 5300M) with AVX2 CPU fallback, FAISS IVF-PQ RAG grounding, and `AGENTS.md` host constraint enforcement.

**Architecture:** A lightweight LangGraph state machine (`StateGraph`) with 4 distinct nodes: `jev_router` (non-autoregressive routing & model tiering), `coder_node` (contextual RAG-grounded code synthesis), `lifeguard_node` (Meta AST validation gating PEP 810 and blocking dangerous side-effects), and `test_verifier` (sandboxed test execution). The engine is wrapped in a Rich TUI CLI with zero-polling execution and bounded memory footprint (<13.6 GB host ceiling).

**Tech Stack:** Python 3.15/3.14, LangGraph, Pydantic v2, FAISS, PyOpenCL / MoltenVK, Clang AVX2 SIMD, macOS Keychain Services (`security`), Rich TUI, Tachyon Profiler (`profiling.sampling`).

**Spec:** `docs/superpowers/specs/2026-10-02-low-resource-swarm-design.md`

## Global Constraints

- Host Profile: MacBookPro16,1, Intel Core i7-9750H (6c/12t, AVX2/FMA, **strictly NO AVX-512**), 16 GB RAM, AMD Radeon Pro 5300M (4GB VRAM), macOS Darwin 26.7.
- Memory Ceiling: Operational Lifeguard monitor terminates spawning and flushes caches if host RAM exceeds 13.6 GB (85% of 16 GB). Baseline cold-start RSS must remain $<40\text{ MB}$.
- Concurrency Cap: Never spawn more than 2–3 active concurrent subagents to prevent CPU/RAM saturation.
- Secret Management: Zero plaintext API keys on disk. Retrieve `OPENAI_API_KEY` from macOS Keychain Services (`security find-generic-password`).
- Tooling Preferences: Generated shell scripts and commands must use modern CLI tools (`rg`, `bat`, `fd`, `sd`, `choose`, `eza`) rather than legacy Unix tools (`grep`, `cat`, `find`, `sed`, `awk`).
- Toolchain: Clang 23.1.1 at `~/.local/opt/llvm-23.1.1`, Apple CLT headers, Python commit-pinned at `~/.local/opt/python-3.15-g6413901`.

## Review Focus

- Malformed / Prohibited AST: Code synthesized with top-level `os.system`, `subprocess.run`, or `eval` must be rejected immediately by Lifeguard with `BLOCKED` status and routed back to Coder.
- Keychain Absence: If `OPENAI_API_KEY` is not found in macOS Keychain, the CLI must provide a clear, non-crashing prompt directing the user to run `low-swarm vault set`.
- GPU Context Failure: If OpenCL initialization fails or GPU memory is saturated, the dispatcher must fall back silently to the native C++/AVX2 SIMD kernel with zero crashes.
- Infinite Resynthesis Loops: If code fails tests or AST checks repeatedly, the iteration circuit breaker must halt execution at exactly 3 loops and return diagnostic errors.
- Unbounded Memory Expansion: Long ingestion runs must use FAISS IVF-PQ (64 bytes/vector) to ensure memory consumption stays under 50 MB for $>100,000$ vectors.

---

## Tasks

### Task 1: RuleEngine & AGENTS.md Invariant Loader

**Files:**
- Create: `src/swarm_sdk/core/rules.py`
- Test: `tests/test_rules.py`

- [ ] Write failing test in `tests/test_rules.py` verifying parsing of host profile (Intel i7-9750H, 16GB, AVX2, max 2-3 subagents) and tool preferences from `AGENTS.md`.
- [ ] Run test to verify failure (`pytest tests/test_rules.py`).
- [ ] Implement `HostRuleEngine` in `src/swarm_sdk/core/rules.py`:
  - `discover_rules()`: Finds `/Users/usuario/AGENTS.md` and `/Users/usuario/Swarm/Agents/coordination.yaml`.
  - `parse_invariants()`: Extracts CPU model, RAM limit (13.6 GB), concurrency cap (3), and disallowed instructions (`AVX-512`).
  - `inject_system_prompt()`: Returns standardized system prompt prefix with host constraints.
- [ ] Run test to verify it passes (`pytest tests/test_rules.py`).
- [ ] Commit: `git add src/swarm_sdk/core/rules.py tests/test_rules.py && git commit -m "feat(rules): add HostRuleEngine for AGENTS.md dynamic enforcement"`

---

### Task 2: VaultKeyManager Integration for OpenAI & Jev

**Files:**
- Modify: `src/swarm_sdk/vault.py`
- Test: `tests/test_vault_keys.py`

- [ ] Write failing test in `tests/test_vault_keys.py` asserting `get_openai_key()` and `set_openai_key()` query and write to macOS Keychain with service name `swarm/OPENAI_API_KEY`.
- [ ] Run test to verify failure (`pytest tests/test_vault_keys.py`).
- [ ] Implement helper methods in `src/swarm_sdk/vault.py`:
  - `get_secret(name: str, fallback_env: bool = True) -> str | None`: Queries process environment, falls back to macOS Keychain (`security find-generic-password -s "swarm/<NAME>"`).
  - `set_secret(name: str, secret_value: str) -> bool`: Executes `/usr/bin/security add-generic-password -s "swarm/<NAME>" -a "$USER" -w "<secret>" -U`.
  - Ensure secret values are never logged or echoed in exceptions.
- [ ] Run test to verify it passes (`pytest tests/test_vault_keys.py`).
- [ ] Commit: `git add src/swarm_sdk/vault.py tests/test_vault_keys.py && git commit -m "feat(vault): add macOS Keychain secret storage for OpenAI and Jev"`

---

### Task 3: Meta Lifeguard AST Pre-Flight Auditor

**Files:**
- Create: `src/swarm_sdk/core/lifeguard_ast.py`
- Test: `tests/test_lifeguard_ast.py`

- [ ] Write failing test in `tests/test_lifeguard_ast.py` testing detection of top-level `subprocess`, `os.system`, `eval`, and un-lazy third-party imports.
- [ ] Run test to verify failure (`pytest tests/test_lifeguard_ast.py`).
- [ ] Implement `MetaLifeguardAuditor(ast.NodeVisitor)` in `src/swarm_sdk/core/lifeguard_ast.py`:
  - `audit_code(code: str) -> LifeguardAuditReport`: Inspects AST.
  - Flags top-level dangerous function calls outside of `def` or `if __name__ == '__main__':`.
  - Flags non-lazy heavy module imports (`torch`, `pandas`, `transformers`) when PEP 810 compliance is active.
  - Returns structured `LifeguardAuditReport` (`is_approved: bool`, `violations: list[str]`).
- [ ] Run test to verify it passes (`pytest tests/test_lifeguard_ast.py`).
- [ ] Commit: `git add src/swarm_sdk/core/lifeguard_ast.py tests/test_lifeguard_ast.py && git commit -m "feat(lifeguard): implement Meta Lifeguard AST pre-flight auditor"`

---

### Task 4: Jev AI System-1 Non-Autoregressive Decision Engine

**Files:**
- Create: `src/swarm_sdk/core/jev_router.py`
- Test: `tests/test_jev_router.py`

- [ ] Write failing test in `tests/test_jev_router.py` verifying `evaluate_noul()`, `evaluate_score()`, and `evaluate_choice()` execute in $<35\text{ms}$ with typed Pydantic models.
- [ ] Run test to verify failure (`pytest tests/test_jev_router.py`).
- [ ] Implement `JevRouter` in `src/swarm_sdk/core/jev_router.py`:
  - `evaluate_noul(task: str) -> NoulDecision`: Binary safety check.
  - `evaluate_score(task: str) -> ScoreDecision`: Calibrated complexity score $\in [0.0, 1.0]$ mapping to model tier (`flash_lite`, `flash`, `pro`).
  - `evaluate_choice(task: str, options: list[str]) -> ChoiceDecision`: Direct discrete routing.
  - Fast local semantic table fallback executing in $<5\text{ms}$ if remote Jev microservice times out.
- [ ] Run test to verify it passes (`pytest tests/test_jev_router.py`).
- [ ] Commit: `git add src/swarm_sdk/core/jev_router.py tests/test_jev_router.py && git commit -m "feat(jev): implement System-1 non-autoregressive decision engine"`

---

### Task 5: Dual-Mode GPU/CPU Vector Dispatcher with PEP 810 Lazy Imports

**Files:**
- Create: `src/swarm_sdk/gpu/lazy_dispatcher.py`
- Test: `tests/test_lazy_dispatcher.py`

- [ ] Write failing test in `tests/test_lazy_dispatcher.py` testing lazy module loading and automatic CPU AVX2 fallback.
- [ ] Run test to verify failure (`pytest tests/test_lazy_dispatcher.py`).
- [ ] Implement `VectorComputeDispatcher` in `src/swarm_sdk/gpu/lazy_dispatcher.py`:
  - Uses `LazyModuleProxy` to defer `pyopencl` import until explicitly needed.
  - Checks available OpenCL platforms for AMD Radeon Pro 5300M.
  - Executes batch dot-product kernel on OpenCL command queue for large matrices.
  - Falls back to native C++ AVX2 SIMD (`compute_vector_dot_product_avx2`) if GPU is unavailable or $N < 1,000$.
- [ ] Run test to verify it passes (`pytest tests/test_lazy_dispatcher.py`).
- [ ] Commit: `git add src/swarm_sdk/gpu/lazy_dispatcher.py tests/test_lazy_dispatcher.py && git commit -m "feat(gpu): add dual-mode GPU/CPU vector dispatcher with lazy imports"`

---

### Task 6: Grounded RAG Ingestion Pipeline with FAISS IVF-PQ

**Files:**
- Create: `src/swarm_sdk/retrieval/rag_ingest.py`
- Test: `tests/test_rag_ingest.py`

- [ ] Write failing test in `tests/test_rag_ingest.py` verifying document chunking, FAISS IVF-PQ quantization ($M=64, K^*=256$), and query retrieval.
- [ ] Run test to verify failure (`pytest tests/test_rag_ingest.py`).
- [ ] Implement `RAGIngestionPipeline` in `src/swarm_sdk/retrieval/rag_ingest.py`:
  - `ingest_documents(paths: list[str])`: Contextual chunking of Markdown documents.
  - `build_ivfpq_index(embeddings: np.ndarray)`: Builds compressed FAISS index.
  - `query(text: str, top_k: int = 5)`: Returns grounded contextual snippets.
- [ ] Run test to verify it passes (`pytest tests/test_rag_ingest.py`).
- [ ] Commit: `git add src/swarm_sdk/retrieval/rag_ingest.py tests/test_rag_ingest.py && git commit -m "feat(rag): add FAISS IVF-PQ grounded ingestion pipeline"`

---

### Task 7: LangGraph Swarm State Machine (`LowSwarmEngine`)

**Files:**
- Create: `src/swarm_sdk/orchestrator/low_swarm.py`
- Test: `tests/test_low_swarm.py`

- [ ] Write failing test in `tests/test_low_swarm.py` asserting end-to-end graph execution, node routing, and 3-iteration circuit breaker.
- [ ] Run test to verify failure (`pytest tests/test_low_swarm.py`).
- [ ] Implement `LowSwarmEngine` in `src/swarm_sdk/orchestrator/low_swarm.py`:
  - Defines `SwarmState` schema.
  - Assembles `StateGraph`:
    - `jev_router_node`: Routes task and sets model tier.
    - `coder_node`: Synthesizes code patches using grounded RAG context.
    - `lifeguard_node`: Runs `MetaLifeguardAuditor`. Conditional edge: if blocked, increments `iteration` and loops back to `coder_node` (max 3 times).
    - `test_verifier_node`: Runs syntax/pytest checks on approved code.
  - Integrates Operational Lifeguard host memory check before every node transition.
- [ ] Run test to verify it passes (`pytest tests/test_low_swarm.py`).
- [ ] Commit: `git add src/swarm_sdk/orchestrator/low_swarm.py tests/test_low_swarm.py && git commit -m "feat(orchestrator): build LowSwarmEngine LangGraph state machine"`

---

### Task 8: Low-Swarm CLI Entrypoint with Rich TUI

**Files:**
- Create: `src/swarm_sdk/cli.py`
- Modify: `pyproject.toml` (add `[project.scripts] low-swarm = "swarm_sdk.cli:main"`)
- Test: `tests/test_cli.py`

- [ ] Write failing test in `tests/test_cli.py` testing CLI argument parsing for `run`, `vault`, `ingest`, and `doctor`.
- [ ] Run test to verify failure (`pytest tests/test_cli.py`).
- [ ] Implement Rich CLI in `src/swarm_sdk/cli.py`:
  - `low-swarm run <task>`: Runs `LowSwarmEngine` with live status spinners, syntax-highlighted diffs, and optional `--profile` flag activating Tachyon sampling.
  - `low-swarm vault set --service openai --key <sk-...>`: Invokes macOS Keychain secret storage.
  - `low-swarm ingest --source ~/Documentos`: Builds FAISS index.
  - `low-swarm doctor`: Inspects host hardware, AGENTS.md rules, and toolchain paths.
- [ ] Run test to verify it passes (`pytest tests/test_cli.py`).
- [ ] Commit: `git add src/swarm_sdk/cli.py pyproject.toml tests/test_cli.py && git commit -m "feat(cli): add low-swarm Rich TUI command-line entrypoint"`

---

### Task 9: End-to-End System Validation & Tachyon Benchmark Run

**Files:**
- Test: `tests/test_e2e_benchmark.py`

- [ ] Write end-to-end integration test in `tests/test_e2e_benchmark.py` synthesizing a sample zero-copy function in a temporary directory.
- [ ] Execute test and assert:
  - Jev System-1 routing completes in $<35\text{ms}$.
  - Meta Lifeguard approves the synthesized code.
  - Test validator passes.
  - Peak resident memory (RSS) remains $<45\text{ MB}$.
- [ ] Run full test suite: `pytest -v tests/`.
- [ ] Commit: `git add tests/test_e2e_benchmark.py && git commit -m "test(e2e): add end-to-end validation and memory benchmark test"`
