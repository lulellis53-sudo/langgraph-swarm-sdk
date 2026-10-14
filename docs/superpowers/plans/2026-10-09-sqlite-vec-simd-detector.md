# Native sqlite-vec AVX/AVX2 SIMD Auto-Detector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement dynamic CPU instruction set feature detection (AVX2/FMA vs AVX1/scalar) in `src/swarm_sdk/memory/sqlite_vec.py` to prevent `Illegal instruction` (`SIGILL`) crashes on non-AVX2 hosts (Lenovo ThinkPad T430 Ivy Bridge) while preserving hardware SIMD quantization speedups on AVX2 hosts (Xeon E5-2694).

**Architecture:** Add `detect_cpu_simd_features()` to `swarm_sdk.memory.sqlite_vec` using NumPy CPU introspection (`numpy.lib.introspect.opt_func_info`) and `ctypes` CPUID fallback checks. Pass the detected feature set to `SqliteVecStore.__init__` to select between quantized `vec0` INT8 tables and safe `float32` / fallback stores.

**Tech Stack:** Python 3.14+, NumPy 2.x, SQLite, sqlite-vec, ctypes.

**Spec:** Option A from brainstorming — dynamic CPUID SIMD detection with hardware fallback gating.

---

## Global Constraints

- **Strict No AVX2 Violation on Legacy**: Must not invoke `vec_quantize_int8` instructions if AVX2 is absent.
- **Backwards Compatibility**: Keep `SqliteVecStore` signature and public methods compatible.
- **Zero Regression**: Preserve existing test suite pass rate.

---

## Tasks

### Task 1: Add `detect_cpu_simd_features` Helper & Fallback Logic

**Files:**
- Modify: `src/swarm_sdk/memory/sqlite_vec.py`
- Test: `tests/test_sqlite_vec_simd.py`

**Interfaces:**
- Produces: `detect_cpu_simd_features() -> dict[str, bool]` returning `{"avx2": bool, "fma": bool, "avx512": bool}`.

- [ ] **Step 1: Write the failing unit test**

```python
# tests/test_sqlite_vec_simd.py
import pytest
from swarm_sdk.memory.sqlite_vec import detect_cpu_simd_features

def test_detect_cpu_simd_features_returns_dict():
    features = detect_cpu_simd_features()
    assert isinstance(features, dict)
    assert "avx2" in features
    assert "fma" in features
    assert isinstance(features["avx2"], bool)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sqlite_vec_simd.py -v`
Expected: FAIL with `ImportError: cannot import name 'detect_cpu_simd_features'`

- [ ] **Step 3: Implement `detect_cpu_simd_features` in `src/swarm_sdk/memory/sqlite_vec.py`**

Add CPUID detection using `numpy.lib.introspect.opt_func_info` with a `sys.platform` / `ctypes` fallback.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_sqlite_vec_simd.py -v`
Expected: PASS

- [ ] **Step 5: Integrate feature detection into `SqliteVecStore.__init__`**

Gated sqlite-vec initialization: if `not features["avx2"]` and environment override `SWARM_ALLOW_NON_AVX2` is not set, force `self._sqlite_vec = False` to prevent `SIGILL` traps on Ivy Bridge.

- [ ] **Step 6: Verify full test suite and benchmark suite pass**

Run: `uv run pytest tests/test_task_command.py tests/test_agent_benchmarks.py -v`
Expected: PASS (20 passed)
