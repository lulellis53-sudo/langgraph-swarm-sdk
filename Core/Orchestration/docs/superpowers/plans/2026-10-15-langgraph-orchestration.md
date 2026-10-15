# LangGraph Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A planner → researcher → writer agent graph built with LangGraph, using LangChain chat models, with optional LangSmith tracing, run through Pixi.

**Architecture:** One `StateGraph` over a typed state dict. The model and the search function are injected, so the graph runs offline in tests. Tracing comes from environment variables only. The project is a Pixi workspace (`pixi.toml`), not a pyproject.

**Tech Stack:** Python 3.14 (conda-forge channel, osx-64), LangGraph 1.2.x, langchain-core 1.6.x, langsmith 0.14.x, pytest 9.x, Pixi 0.81.

**Spec:** No written spec exists. The design was agreed in conversation on 2026-10-15: one graph, injected model and search, env-only tracing, Pixi manifest. Human review of this plan replaces the spec review.

## Global Constraints

- Manifest: `pixi.toml` only. No `pyproject.toml`.
- Platform: `osx-64` only.
- Python: `3.14.*`.
- Secrets: `LANGSMITH_API_KEY` and model keys are read from the environment. Never written to a file, a test, or a log.
- Installs: `pixi add` and `pixi install` inside this project only. Nothing installed into the home directory.
- Commands: run tests with `pixi run test`.

## Review Focus

1. Dependency that has no macOS Intel (`osx-64`) wheel makes `pixi add` fail. Expected: the add fails with a clear platform message, and the manifest is unchanged.
2. Empty goal string. Expected: the graph still runs each stage and returns an answer. Covered by `test_empty_goal_still_produces_each_stage`.
3. Search backend raises. Expected: the error reaches the caller, not a silent empty research. Covered by `test_search_failure_propagates`.
4. Missing `LANGSMITH_API_KEY` with tracing on. Expected: the graph still runs, and no key is printed. Covered by Task 2.
5. Model returns non-text content. Expected: the answer is still a string. Covered by Task 3.

---

## Status

- [x] Project created with `pixi init` (`Core/Orchestration/pixi.toml`, `osx-64`, `conda-forge`).
- [x] Python 3.14, `langgraph`, `langchain-core`, `langsmith`, `pytest` added.
- [x] `orchestration/graph.py` and `tests/test_graph.py` written; 3 tests pass with `pixi run test`.
- [ ] Remaining packages (`fastembed`, `pydantic`, `tiktoken`, `tokenizers`, `fastapi`, `uvloop`, `httpx2`, `requests`, `sympy`, `pyarrow`, `polars`, `numpy`, `duckdb`, `sqlalchemy`, `rich`, `loguru`, `prometheus-client`): `pixi add` failed on a platform wheel error. Not yet in the manifest.

---

### Task 1: Install the requested packages for osx-64

**Files:**

- Modify: `pixi.toml` (`[pypi-dependencies]`)

**Interfaces:**

- Consumes: the existing Pixi workspace.
- Produces: a manifest and lock that install on `osx-64`. Later tasks rely on `pixi run test` working.
- [ ] **Step 1: Find the package without an osx-64 wheel**

Run: `pixi add --pypi fastembed pydantic tiktoken tokenizers fastapi uvloop httpx2 requests sympy pyarrow polars numpy duckdb sqlalchemy rich loguru prometheus-client 2>&1 | head -40`
Expected: an error that names one package and lists the platforms it has wheels for (arm64, win, manylinux).

- [ ] **Step 2: Add the packages without that one**

Run the same `pixi add --pypi` command with the failing package removed.
Expected: all remaining packages are added, and `pixi.toml` lists them under `[pypi-dependencies]`.

- [ ] **Step 3: Check the manifest**

Run: `sed -n '/\[pypi-dependencies\]/,$p' pixi.toml`
Expected: the four original packages plus every package added in Step 2.

- [ ] **Step 4: Run the existing tests**

Run: `pixi run test`
Expected: `3 passed`.

- [ ] **Step 5: Record the removed package**

Write the name of the package removed in Step 1 and the wheel platforms it lacks into the Status section of this plan.

---

### Task 2: LangSmith tracing from the environment

**Files:**

- Create: `orchestration/tracing.py`
- Test: `tests/test_tracing.py`

**Interfaces:**

- Consumes: none.
- Produces: `tracing_enabled() -> bool`, which returns `True` only when `LANGSMITH_TRACING` is `"true"` and `LANGSMITH_API_KEY` is set.
- [ ] **Step 1: Write the failing test**

```python
# tests/test_tracing.py
from __future__ import annotations

import pytest
from orchestration.tracing import tracing_enabled


def test_disabled_without_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.setenv("LANGSMITH_API_KEY", "not-printed")
    assert tracing_enabled() is False


def test_disabled_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    assert tracing_enabled() is False


def test_enabled_with_flag_and_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "not-printed")
    assert tracing_enabled() is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pixi run python -m pytest tests/test_tracing.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'orchestration.tracing'`

- [ ] **Step 3: Write minimal implementation**

```python
# orchestration/tracing.py
"""LangSmith tracing switch. Reads the environment only; never stores a key."""

from __future__ import annotations

import os


def tracing_enabled() -> bool:
    """Return True when LangSmith tracing is switched on and a key is present.

    Returns:
        True if ``LANGSMITH_TRACING`` is ``"true"`` and ``LANGSMITH_API_KEY`` is non-empty.
    """
    flag = os.environ.get("LANGSMITH_TRACING", "").strip().lower() == "true"
    key = os.environ.get("LANGSMITH_API_KEY", "").strip()
    return flag and bool(key)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pixi run python -m pytest tests/test_tracing.py -q`
Expected: `3 passed`

- [ ] **Step 5: Commit**

Commit only if the project is under git and you have been asked to commit. Otherwise skip this step.

---

### Task 3: Normalize model output to text

**Files:**

- Modify: `orchestration/graph.py` (add `_as_text`, use it in the three nodes)
- Test: `tests/test_graph.py` (add one test)

**Interfaces:**

- Consumes: `build_graph(llm, search)` from `orchestration/graph.py`.
- Produces: every node returns a `str` even when the model returns a list of content blocks.
- [ ] **Step 1: Write the failing test**

Add this test to `tests/test_graph.py`:

```python
from langchain_core.messages import AIMessage

from orchestration.graph import build_graph


def test_list_content_is_joined_to_text() -> None:

    class BlockModel:
        def invoke(self, messages):
            return AIMessage(
                content=[{"type": "text", "text": "block "}, {"type": "text", "text": "answer"}]
            )

    result = build_graph(BlockModel(), lambda plan: "notes").invoke({"goal": "x"})

    assert result["answer"] == "block answer"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pixi run python -m pytest tests/test_graph.py::test_list_content_is_joined_to_text -q`
Expected: FAIL. The answer is the list's string form, not `"block answer"`.

- [ ] **Step 3: Write minimal implementation**

In `orchestration/graph.py`, add above `build_graph`:

```python
def _as_text(content: object) -> str:
    """Join LangChain message content into one string.

    Args:
        content: A string, or a list of content blocks with ``text`` fields.

    Returns:
        The text of the message.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block) for block in content
        )
    return str(content)
```

Then replace each `str(reply.content)` in `planner` and `writer` with `_as_text(reply.content)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pixi run test`
Expected: `5 passed` (the 3 existing tests and the 2 new ones from Tasks 2–3).

- [ ] **Step 5: Commit**

Commit only if the project is under git and you have been asked to commit. Otherwise skip this step.

---

## Self-Review

1. **Spec coverage:** the spec is the conversation. Graph (done), injected model and search (done), env-only tracing (Task 2), Pixi manifest (done), requested packages (Task 1).
2. **Placeholder scan:** no TBD or TODO. Step 5 of Task 1 names the removed package at run time, by design.
3. **Type consistency:** `build_graph(llm, search)`, `OrchestrationState`, `SearchFn`, `tracing_enabled() -> bool`, `_as_text(content) -> str`.
4. **Review Focus:** each of the five lines maps to a test or a Task 1 step.

---

## Execution

Plan saved to `docs/superpowers/plans/2026-10-15-langgraph-orchestration.md`. No execution method has been chosen yet.
