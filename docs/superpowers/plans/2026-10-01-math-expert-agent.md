# Math Expert Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade `ModelDelegate/MathWorker` into a first-class Math Expert Agent combining analytical reasoning, SymPy computational verification, multi-tiered LLM routing, and hardware-accelerated OpenCL GPU vector dispatch.

**Architecture:** Add structured math problem/result models and a hardware-aware crossover classifier in `src/swarm_sdk/math/`. Update `Agents/ModelDelegate/MathWorker/`'s contract (`AGENTS.md`) and manifest (`agent.yaml`) to support both delegation dispatch and end-to-end mathematical solving. Wire into `coordination.yaml` and test against the benchmark suite.

**Tech Stack:** Python >=3.14.5, uv, pytest, ruff, ty, NumPy, SymPy, pyopencl, LangChain / LangGraph.

**Spec:** `docs/superpowers/specs/2026-10-01-math-expert-agent-design.md`

## Global Constraints

- Python `>=3.14.5`, managed with uv; run commands as `uv run --extra dev ...`.
- Every new module begins with a docstring, then immediately `from __future__ import annotations`.
- Ruff `line-length = 100`, `target-version = "py314"`, rules `E,F,I,UP`. No new `# noqa` or `# type: ignore` without a named rule and reason.
- No new external runtime dependencies (`sympy` and `numpy` are already in `pyproject.toml`).
- Backward-compatible: `ModelDelegate/MathWorker` keeps returning `selected_route`, `gpu_enabled`, `backend`, and `notes`.
- Quality gate passes cleanly:
  ```bash
  uv run --extra dev pytest Agents/benchmark -q --tb=short
  uv run --extra dev ruff check src Agents/benchmark Main
  uv run --extra dev ty check src Agents/benchmark Main
  uv run python -m swarm_sdk.agents.validate
  ```

## Review Focus

1. Matrix below 8,192 rows without a resident buffer routes to CPU NumPy BLAS even when GPU is available (avoids PCIe overhead).
2. Matrix with >= 8,192 rows or a cached buffer key routes to `opencl` when `SWARM_GPU_BACKEND` is set.
3. Proof or symbolic calculus tasks select high-reasoning routes (`think_level: high` or `xhigh`).
4. Mathematical solver output formats closed-form solutions in valid LaTeX alongside reproducible Python verification snippets.
5. Zero-dimension or empty vector inputs return gracefully without division-by-zero or crashes.

---

### Task 1: Math Problem Models & Types

**Files:**
- Create: `src/swarm_sdk/math/types.py`
- Modify: `src/swarm_sdk/math/__init__.py`
- Test: `Agents/benchmark/tests/test_math_types.py`

**Interfaces:**
- Produces: `MathTaskType`, `MathMode`, `MathProblem`, `MathResult`, `VerificationResult`, `MathDispatchDecision`.

- [ ] **Step 1: Write the failing tests** (`Agents/benchmark/tests/test_math_types.py`)

```python
"""Tests for math problem models and contract types."""

from __future__ import annotations

from swarm_sdk.math.types import (
    MathDispatchDecision,
    MathMode,
    MathProblem,
    MathResult,
    VerificationResult,
)


def test_math_problem_defaults() -> None:
    prob = MathProblem(
        problem_statement="Solve 2x + 4 = 10",
        task_type="arithmetic",
    )
    assert prob.mode == "solve"
    assert prob.precision_tolerance == 1e-6
    assert prob.force_gpu is False


def test_math_dispatch_decision_roundtrip() -> None:
    decision = MathDispatchDecision(
        backend="opencl",
        gpu_enabled=True,
        selected_route={"name": "opencl_math", "provider": "local_gpu"},
        notes="Rows exceed threshold",
    )
    assert decision.backend == "opencl"
    assert decision.gpu_enabled is True
    data = decision.model_dump()
    assert data["backend"] == "opencl"


def test_math_result_serialization() -> None:
    res = MathResult(
        task_id="T1",
        status="done",
        mode="solve",
        selected_route={"name": "mistral:ministral-3-8b-latest", "provider": "mistral-2"},
        gpu_enabled=False,
        backend="llm",
        solution={
            "formulation": "Linear equation",
            "derivation": "2x = 6 => x = 3",
            "latex": "x = 3",
            "result": 3.0,
        },
        verification=VerificationResult(
            verified=True,
            method="sympy",
            script_snippet="assert 2*3 + 4 == 10",
            error_bound=0.0,
        ),
        notes="Exact solution",
    )
    assert res.verification.verified is True
    assert res.solution["result"] == 3.0
```

- [ ] **Step 2: Run test to verify failure**

Run: `uv run --extra dev pytest Agents/benchmark/tests/test_math_types.py -q --tb=short`
Expected: FAIL (`ModuleNotFoundError: No module named 'swarm_sdk.math.types'`).

- [ ] **Step 3: Implement `src/swarm_sdk/math/types.py`**

Define Pydantic models:
- `MathMode = Literal["dispatch", "solve", "verify"]`
- `MathTaskType = Literal["matrix", "vector", "stats", "calculus", "optimization", "arithmetic", "proof"]`
- `MathProblem(BaseModel)`: statement, task_type, mode, shape, tolerance, force_gpu, think_level.
- `VerificationResult(BaseModel)`: verified, method, script_snippet, error_bound.
- `MathDispatchDecision(BaseModel)`: backend, gpu_enabled, selected_route, notes.
- `MathResult(BaseModel)`: task_id, status, mode, selected_route, gpu_enabled, backend, solution, verification, notes.
Re-export in `src/swarm_sdk/math/__init__.py`.

- [ ] **Step 4: Run test to verify pass**

Run: `uv run --extra dev pytest Agents/benchmark/tests/test_math_types.py -q --tb=short`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/swarm_sdk/math/types.py src/swarm_sdk/math/__init__.py Agents/benchmark/tests/test_math_types.py
git commit -m "feat(math): add math problem and result contract models"
```

---

### Task 2: Hardware-Aware Crossover & Dispatch Classifier

**Files:**
- Create: `src/swarm_sdk/math/dispatch.py`
- Modify: `src/swarm_sdk/math/__init__.py`
- Test: `Agents/benchmark/tests/test_math_dispatch.py`

**Interfaces:**
- Consumes: `MathProblem`, `MathDispatchDecision` (Task 1), `opencl_available` from `swarm_sdk.gpu`.
- Produces: `classify_math_task(problem: MathProblem, *, has_cache_key: bool = False) -> MathDispatchDecision`.

- [ ] **Step 1: Write the failing tests** (`Agents/benchmark/tests/test_math_dispatch.py`)

```python
"""Tests for hardware-aware math dispatch and crossover heuristics."""

from __future__ import annotations

import pytest

from swarm_sdk.math.dispatch import classify_math_task
from swarm_sdk.math.types import MathProblem


def test_small_matrix_routes_to_numpy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SWARM_GPU_BACKEND", "opencl")
    prob = MathProblem(
        problem_statement="Multiply 256x256 matrices",
        task_type="matrix",
        shape=(256, 256),
    )
    decision = classify_math_task(prob)
    assert decision.backend == "numpy"
    assert decision.gpu_enabled is False


def test_large_matrix_routes_to_gpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SWARM_GPU_BACKEND", "opencl")
    prob = MathProblem(
        problem_statement="Multiply 10000x1024 matrix",
        task_type="matrix",
        shape=(10000, 1024),
    )
    decision = classify_math_task(prob)
    assert decision.backend == "opencl"
    assert decision.gpu_enabled is True


def test_cached_buffer_routes_to_gpu_even_for_medium_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SWARM_GPU_BACKEND", "opencl")
    prob = MathProblem(
        problem_statement="Search resident store",
        task_type="vector",
        shape=(1024, 768),
    )
    decision = classify_math_task(prob, has_cache_key=True)
    assert decision.backend == "opencl"
    assert decision.gpu_enabled is True


def test_formal_proof_routes_to_high_reasoning() -> None:
    prob = MathProblem(
        problem_statement="Prove that the square root of 2 is irrational",
        task_type="proof",
    )
    decision = classify_math_task(prob)
    assert decision.backend == "llm"
    assert decision.selected_route["provider"] in {"claude-code", "google", "codex", "zai"}
```

- [ ] **Step 2: Run test to verify failure**

Run: `uv run --extra dev pytest Agents/benchmark/tests/test_math_dispatch.py -q --tb=short`
Expected: FAIL (`ModuleNotFoundError: No module named 'swarm_sdk.math.dispatch'`).

- [ ] **Step 3: Implement `classify_math_task` in `src/swarm_sdk/math/dispatch.py`**

Logic:
1. If `task_type in {"matrix", "vector"}`:
   - Check if GPU backend is enabled (`SWARM_GPU_BACKEND` or `force_gpu`).
   - If enabled and (shape rows >= 8192 or `has_cache_key`): return backend `opencl`/`molten` with `gpu_enabled=True`.
   - Otherwise return backend `numpy` with `gpu_enabled=False`.
2. If `task_type in {"proof", "calculus", "optimization"}`:
   - Return backend `llm` with frontier route (`claude-code:claude-3-7-sonnet` or `google:gemini-2.5-pro` or `zai:glm-5.3`) with high reasoning.
3. If `task_type == "arithmetic"`:
   - Return backend `llm` with `mistral:ministral-3-8b-latest` (fast, low cost).
4. If `task_type == "stats"`:
   - Return backend `llm` with `openai:gpt-4o-mini` (balanced).

- [ ] **Step 4: Run test to verify pass**

Run: `uv run --extra dev pytest Agents/benchmark/tests/test_math_dispatch.py -q --tb=short`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/swarm_sdk/math/dispatch.py src/swarm_sdk/math/__init__.py Agents/benchmark/tests/test_math_dispatch.py
git commit -m "feat(math): add crossover classification and hardware dispatch logic"
```

---

### Task 3: Computational Verification Engine

**Files:**
- Create: `src/swarm_sdk/math/verify.py`
- Modify: `src/swarm_sdk/math/__init__.py`
- Test: `Agents/benchmark/tests/test_math_verify.py`

**Interfaces:**
- Produces: `verify_math_solution(claim: str, expected: float | int | str, script: str) -> VerificationResult`.

- [ ] **Step 1: Write the failing tests** (`Agents/benchmark/tests/test_math_verify.py`)

```python
"""Tests for computational mathematical verification."""

from __future__ import annotations

from swarm_sdk.math.verify import verify_math_solution


def test_verify_symbolic_solution() -> None:
    res = verify_math_solution(
        claim="Derivative of x^2 is 2x",
        expected="2*x",
        script="import sympy as sp; x = sp.Symbol('x'); res = str(sp.diff(x**2, x))",
    )
    assert res.verified is True
    assert res.method == "sympy"


def test_verify_numerical_solution_within_tolerance() -> None:
    res = verify_math_solution(
        claim="Sum of 1/2^n from 1 to 10 is approx 0.999",
        expected=0.9990234375,
        script="res = sum(1/(2**n) for n in range(1, 11))",
    )
    assert res.verified is True
    assert res.error_bound < 1e-5
```

- [ ] **Step 2: Run test to verify failure**

Run: `uv run --extra dev pytest Agents/benchmark/tests/test_math_verify.py -q --tb=short`
Expected: FAIL (`ModuleNotFoundError: No module named 'swarm_sdk.math.verify'`).

- [ ] **Step 3: Implement `verify_math_solution` in `src/swarm_sdk/math/verify.py`**

Execute verification in a restricted execution namespace with `sympy`, `numpy`, and `math` available. Compare `res` against `expected` considering numerical tolerances (`abs(val - exp) <= 1e-5`).

- [ ] **Step 4: Run test to verify pass**

Run: `uv run --extra dev pytest Agents/benchmark/tests/test_math_verify.py -q --tb=short`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/swarm_sdk/math/verify.py src/swarm_sdk/math/__init__.py Agents/benchmark/tests/test_math_verify.py
git commit -m "feat(math): add computational verification engine"
```

---

### Task 4: Upgrade MathWorker Agent Contract and Manifest

**Files:**
- Modify: `Agents/ModelDelegate/MathWorker/AGENTS.md`
- Modify: `Agents/ModelDelegate/MathWorker/agent.yaml`
- Test: `Agents/benchmark/tests/test_math_worker_manifest.py`

**Interfaces:**
- Validated by: `swarm_sdk.agents.validate.load_agent_manifest`

- [ ] **Step 1: Write the failing tests** (`Agents/benchmark/tests/test_math_worker_manifest.py`)

```python
"""Tests validating MathWorker manifest and role contract standards."""

from __future__ import annotations

from pathlib import Path

from swarm_sdk.agents.manifest import load_agent_manifest


def test_math_worker_manifest_spec() -> None:
    path = (
        Path(__file__).resolve().parents[3]
        / "Agents"
        / "ModelDelegate"
        / "MathWorker"
        / "agent.yaml"
    )
    manifest = load_agent_manifest(path)
    assert manifest.name == "ModelDelegate/MathWorker"
    assert manifest.role == "delegate_math"
    task_ids = {t.id for t in manifest.tasks}
    assert "delegate_math" in task_ids
    assert "solve_math" in task_ids
    assert "verify_math" in task_ids
    assert "gpu_math" in manifest.capabilities
    assert "symbolic_math" in manifest.capabilities
    assert manifest.token_budget.max_prompt >= 4096
```

- [ ] **Step 2: Run test to verify failure**

Run: `uv run --extra dev pytest Agents/benchmark/tests/test_math_worker_manifest.py -q --tb=short`
Expected: FAIL (`AssertionError: 'solve_math' not in task_ids`).

- [ ] **Step 3: Update `agent.yaml` and `AGENTS.md`**

In `Agents/ModelDelegate/MathWorker/agent.yaml`:
- Add tasks `solve_math` and `verify_math`.
- Add capabilities `symbolic_math`, `numerical_optimization`, `proof_verification`.
- Increase `token_budget` to `max_prompt: 4096`, `max_completion: 2048`.

In `Agents/ModelDelegate/MathWorker/AGENTS.md`:
- Document dual persona: Math Reasoning Specialist + Hardware Dispatcher.
- Specify exact decision rules (crossover at 8,192 rows, SymPy verification).
- Document input and output contracts for both `dispatch` and `solve` modes.

- [ ] **Step 4: Run test and manifest validation**

Run: `uv run --extra dev pytest Agents/benchmark/tests/test_math_worker_manifest.py -q --tb=short`
Run: `uv run python -m swarm_sdk.agents.validate`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add Agents/ModelDelegate/MathWorker/agent.yaml Agents/ModelDelegate/MathWorker/AGENTS.md Agents/benchmark/tests/test_math_worker_manifest.py
git commit -m "feat(agents): elevate MathWorker contract and manifest with dual-mode capabilities"
```

---

### Task 5: Swarm Coordination, Model Delegation Suite Integration & Full Gate

**Files:**
- Modify: `Agents/ModelDelegate/AGENTS.md`
- Modify: `Agents/coordination.yaml`
- Modify: `Agents/benchmark/Tasks/model_delegation/test_model_delegation.py`

**Interfaces:**
- Validates: Model delegation suite and full repository test gates.

- [ ] **Step 1: Write integration assertions** (append to `Agents/benchmark/Tasks/model_delegation/test_model_delegation.py`)

```python
def test_math_dispatch_respects_hardware_crossover(monkeypatch: pytest.MonkeyPatch) -> None:
    from swarm_sdk.math.dispatch import classify_math_task
    from swarm_sdk.math.types import MathProblem

    monkeypatch.setenv("SWARM_GPU_BACKEND", "opencl")
    small = MathProblem(problem_statement="small matrix", task_type="matrix", shape=(256, 256))
    large = MathProblem(problem_statement="large matrix", task_type="matrix", shape=(8192, 1024))

    assert classify_math_task(small).backend == "numpy"
    assert classify_math_task(large).backend == "opencl"
```

- [ ] **Step 2: Update `Agents/ModelDelegate/AGENTS.md` and `Agents/coordination.yaml`**

Update `ModelDelegate` docs and coordination task board to acknowledge MathWorker's enhanced math solving and verification roles.

- [ ] **Step 3: Run targeted integration test**

Run: `uv run --extra dev pytest Agents/benchmark/Tasks/model_delegation/test_model_delegation.py -q --tb=short`
Expected: PASS.

- [ ] **Step 4: Run repository quality gate**

```bash
uv run --extra dev pytest Agents/benchmark/tests/test_math_types.py Agents/benchmark/tests/test_math_dispatch.py Agents/benchmark/tests/test_math_verify.py Agents/benchmark/tests/test_math_worker_manifest.py -q --tb=short
uv run --extra dev ruff check src/swarm_sdk/math Agents/benchmark/tests/test_math*
uv run --extra dev ty check src/swarm_sdk/math Agents/benchmark/tests/test_math*
uv run python -m swarm_sdk.agents.validate
```
Expected: All checks pass with 0 errors.

- [ ] **Step 5: Commit**

```bash
git add Agents/ModelDelegate/AGENTS.md Agents/coordination.yaml Agents/benchmark/Tasks/model_delegation/test_model_delegation.py
git commit -m "feat(coordination): wire enhanced MathWorker into model delegation suite"
```
