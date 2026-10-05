# LangGraph Swarm Production Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the three production-reliability gaps between `Documents/LangSwarm.md` and `src/swarm_sdk`: durable checkpointing, an explicit recursion limit with a clean HTTP error, and a cheap liveness endpoint.

**Architecture:** `SwarmSDK` keeps one compiled `langgraph-swarm` graph. We swap its hard-wired `InMemorySaver` for a factory (`open_checkpointer`) that returns a `SqliteSaver` when `Settings.checkpoint_path` is set, pass `recursion_limit` in every invoke config, and map `GraphRecursionError` to HTTP 508 in `swarm-api`. `/healthz` is added beside the existing `/v1/health`.

**Tech Stack:** Python 3.14, LangGraph >=1.0, `langgraph-checkpoint-sqlite`, FastAPI, pytest (`asyncio_mode = "auto"`), ruff, uv.

**Spec:** `Documents/LangSwarm.md` — §3.2 (durable checkpointing), §5.1 (HTTP service), §16.2 (`/healthz` polled by Lifeguard), §17.1 and §17.5 (recursion limit, production checklist).

## Scope (what is in and out)

The spec is a 2425-line reference covering many independent subsystems, so this plan covers only the swarm-core and serving gaps found by probing the code. Already implemented, no work: `create_swarm` handoffs, wave-barrier DAG with `assert_file_partition`, vault, token budget, semantic cache, tracing, Lifeguard AST audit.

Deliberately NOT in this plan (each deserves its own plan):
- ColBERT/ColPali reranking (§8.2), self-training (§10), Rust/C extensions (§11), mimalloc/Python 3.15 (§13): research-grade, no consumer in the repo.
- Human-in-the-loop `interrupt()` (§3.3): needs a product decision on which actions are high-risk; the checkpointer from Task 1 is its prerequisite.
- `handoff_depth` counter (§17.1): `recursion_limit` (Task 2) is the hard backstop; a counter needs custom graph state and is YAGNI until loops are observed.
- SSE streaming (§4.5/§5): separate plan.

## Global Constraints

- Python `>=3.14`; ruff `line-length = 100`, rules `E,F,I,UP`; type hints on public functions; built-in generics and `X | None`.
- Add dependencies only with `uv add`; never edit `uv.lock` by hand.
- No `# noqa`, `# type: ignore`, skip or xfail without a named rule and reason.
- Tests live in `Agents/benchmark/tests/` (pytest `testpaths`); fakes in `Agents/benchmark/tests/fakes.py`.
- No secrets in code or logs. Commit only on a feature branch (create `feat/langgraph-hardening` first); never force-push.
- Gate before reporting: `uv run ruff format --check && uv run ruff check && uv run python -m compileall -q . && uv run python -m pytest -q --tb=short`.

## Review Focus

- Restart on a persisted thread must keep its `active_agent` (today a new process treats every thread as new and resets it to `researcher`). Tested in Task 1.
- `checkpoint_path` whose parent directory does not exist must be created, not crash at startup. Tested in Task 1.
- The in-memory thread-cap eviction must not delete durable checkpoints from a SQLite store. Tested in Task 1.
- A handoff ping-pong that hits `recursion_limit` must return HTTP 508 with a readable detail, not a 500 traceback. Tested in Task 2.
- `/healthz` must stay 200 and must not call providers while upstream LLMs are down. Tested in Task 3.

---

### Task 1: Durable SQLite checkpointer

**Files:**
- Create: `src/swarm_sdk/core/checkpoint.py`
- Modify: `src/swarm_sdk/config/settings.py:50-56` (add `checkpoint_path`)
- Modify: `src/swarm_sdk/core/swarm.py` (`__init__` lines ~182-185, `_register_thread` ~320-334, `_swarm` ~336-341)
- Modify: `pyproject.toml` (via `uv add`)
- Test: `Agents/benchmark/tests/test_checkpoint.py`

**Interfaces:**
- Consumes: `Settings` (pydantic-settings model), `SwarmSDK` internals above.
- Produces: `open_checkpointer(path: str | None) -> BaseCheckpointSaver` in `swarm_sdk.core.checkpoint`; `Settings.checkpoint_path: str | None = None`; `SwarmSDK._is_new_thread(thread_id: str) -> bool`.

- [ ] **Step 1: Create the feature branch and add the dependency**

```bash
cd ~/Swarm && git switch -c feat/langgraph-hardening
uv add langgraph-checkpoint-sqlite
uv run python -c "from langgraph.checkpoint.sqlite import SqliteSaver; print(SqliteSaver)"
```
Expected: prints the class, no ImportError. (Today this import fails with `No module named 'langgraph.checkpoint.sqlite'`.)

- [ ] **Step 2: Write the failing tests**

```python
# Agents/benchmark/tests/test_checkpoint.py
import operator
from pathlib import Path
from typing import Annotated

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from benchmark.tests.fakes import Script, ScriptedModel, answer
from swarm_sdk.config.settings import Settings
from swarm_sdk.core.checkpoint import open_checkpointer
from swarm_sdk.core.swarm import SwarmSDK
from swarm_sdk.retrieval.embeddings import HashEmbedder
from swarm_sdk.retrieval.rerank import IdentityReranker


class _State(TypedDict):
    log: Annotated[list[str], operator.add]


def _app(saver):
    graph = StateGraph(_State)
    graph.add_node("step", lambda state: {"log": ["x"]})
    graph.add_edge(START, "step")
    graph.add_edge("step", END)
    return graph.compile(checkpointer=saver)


def _sdk(tmp_path: Path, checkpoint: Path, *, max_threads: int = 200) -> SwarmSDK:
    model = ScriptedModel(script=Script([answer("ok")]))
    settings = Settings(
        memory_path=str(tmp_path / "mem.db"),
        cache_path=str(tmp_path / "cache.db"),
        checkpoint_path=str(checkpoint),
        embed_dim=32,
        memory_backend="opencl",
    )
    return SwarmSDK(
        settings,
        router_model=model,
        specialist_model=model,
        embedder=HashEmbedder(32),
        reranker=IdentityReranker(),
        max_threads=max_threads,
    )


def test_none_path_is_in_memory() -> None:
    assert type(open_checkpointer(None)).__name__ == "InMemorySaver"


def test_sqlite_checkpoint_survives_reopen(tmp_path: Path) -> None:
    path = str(tmp_path / "cp.db")
    config = {"configurable": {"thread_id": "t1"}}
    _app(open_checkpointer(path)).invoke({"log": []}, config)
    state = _app(open_checkpointer(path)).get_state(config)
    assert state.values["log"] == ["x"]


def test_missing_parent_directory_is_created(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "er" / "cp.db"
    open_checkpointer(str(path))
    assert path.exists()


def test_restart_keeps_existing_thread(tmp_path: Path) -> None:
    checkpoint = tmp_path / "cp.db"
    config = {"configurable": {"thread_id": "t"}}
    first = _sdk(tmp_path, checkpoint)
    assert first._is_new_thread("t") is True
    _app(first._checkpointer).invoke({"log": []}, config)
    second = _sdk(tmp_path, checkpoint)
    assert second._is_new_thread("t") is False
    assert second._is_new_thread("other") is True


def test_eviction_does_not_delete_durable_checkpoints(tmp_path: Path) -> None:
    checkpoint = tmp_path / "cp.db"
    sdk = _sdk(tmp_path, checkpoint, max_threads=2)
    _app(sdk._checkpointer).invoke({"log": []}, {"configurable": {"thread_id": "keep"}})
    for name in ("keep", "b", "c"):  # third id pushes past the cap and evicts "keep"
        sdk._register_thread(name)
    assert sdk._is_new_thread("keep") is False
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run python -m pytest Agents/benchmark/tests/test_checkpoint.py -q --tb=short -x`
Expected: FAIL with `ModuleNotFoundError: No module named 'swarm_sdk.core.checkpoint'`.

- [ ] **Step 4: Implement the factory and setting**

```python
# src/swarm_sdk/core/checkpoint.py
"""Checkpointer factory: durable SQLite when a path is configured, else in-memory."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from langgraph.checkpoint.base import BaseCheckpointSaver


def open_checkpointer(path: str | None) -> BaseCheckpointSaver:
    """Open the LangGraph checkpointer for swarm threads.

    Args:
        path: SQLite file path, or ``None`` for a process-local in-memory saver.

    Returns:
        A ``SqliteSaver`` (parent directories created) or an ``InMemorySaver``.
    """
    if path is None:
        from langgraph.checkpoint.memory import InMemorySaver

        return InMemorySaver()
    from langgraph.checkpoint.sqlite import SqliteSaver

    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    # The graph runs in worker threads (offload); SqliteSaver serialises writes with its own lock.
    return SqliteSaver(sqlite3.connect(target, check_same_thread=False))


__all__ = ["open_checkpointer"]
```

In `src/swarm_sdk/config/settings.py`, after `cache_path: str = "swarm-cache.sqlite"` add:

```python
    # None keeps checkpoints in memory (lost on restart); a path makes threads durable.
    checkpoint_path: str | None = None
```

- [ ] **Step 5: Wire it into `SwarmSDK`**

In `src/swarm_sdk/core/swarm.py` `__init__`, replace the `InMemorySaver` import and assignment:

```python
        from swarm_sdk.core.checkpoint import open_checkpointer

        self._compiled: CompiledGraph | None = None
        self._checkpointer = open_checkpointer(self.settings.checkpoint_path)
```

Add the method next to `_register_thread`:

```python
    def _is_new_thread(self, thread_id: str) -> bool:
        """True when the checkpointer holds no state for ``thread_id`` (survives restarts)."""
        config = {"configurable": {"thread_id": thread_id}}
        return self._checkpointer.get_tuple(config) is None
```

Change `_register_thread` so it only tracks ids and never deletes durable state: remove the `delete = getattr(self._checkpointer, "delete_thread", None)` block, and instead delete only for the in-memory saver:

```python
                for stale in list(self._threads)[:drop]:
                    del self._threads[stale]
                    if self.settings.checkpoint_path is None:
                        self._checkpointer.delete_thread(stale)
```

In `_swarm`, replace `if self._register_thread(thread_id):` with:

```python
        self._register_thread(thread_id)
        if self._is_new_thread(thread_id):
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run python -m pytest Agents/benchmark/tests/test_checkpoint.py Agents/benchmark/tests/test_swarm.py -q --tb=short`
Expected: all PASS (existing swarm tests prove the in-memory path is unchanged).

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff format src/swarm_sdk/core/checkpoint.py src/swarm_sdk/core/swarm.py src/swarm_sdk/config/settings.py Agents/benchmark/tests/test_checkpoint.py
uv run ruff check src Agents/benchmark/tests/test_checkpoint.py
git add pyproject.toml uv.lock src/swarm_sdk/core/checkpoint.py src/swarm_sdk/core/swarm.py src/swarm_sdk/config/settings.py Agents/benchmark/tests/test_checkpoint.py
git commit -m "feat(swarm): durable SQLite checkpointer behind Settings.checkpoint_path" \
  -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Recursion limit and HTTP 508 on handoff loops

**Files:**
- Modify: `src/swarm_sdk/config/settings.py` (add `recursion_limit`)
- Modify: `src/swarm_sdk/core/swarm.py` (`_swarm` invoke config)
- Modify: `src/swarm_sdk/serving/http.py` (`runs` handler)
- Test: `Agents/benchmark/tests/test_recursion_limit.py`

**Interfaces:**
- Consumes: Task 1's `SwarmSDK` (unchanged signatures); `create_app(sdk)` from `swarm_sdk.serving.http`.
- Produces: `Settings.recursion_limit: int` (default 50, `ge=2`); `SwarmSDK._run_config(thread_id: str) -> dict[str, object]`; HTTP 508 with `{"detail": "handoff loop: recursion limit reached"}` from `POST /v1/runs`.

- [ ] **Step 1: Write the failing tests**

```python
# Agents/benchmark/tests/test_recursion_limit.py
from pathlib import Path

from fastapi.testclient import TestClient
from langgraph.errors import GraphRecursionError

from benchmark.tests.fakes import Script, ScriptedModel, answer
from swarm_sdk.config.settings import Settings
from swarm_sdk.core.swarm import SwarmSDK
from swarm_sdk.retrieval.embeddings import HashEmbedder
from swarm_sdk.retrieval.rerank import IdentityReranker
from swarm_sdk.serving.http import create_app


class _LoopingSDK:
    async def run(self, text: str, thread_id: str = "default"):
        raise GraphRecursionError("Recursion limit of 50 reached")


def test_run_config_carries_recursion_limit(tmp_path: Path) -> None:
    model = ScriptedModel(script=Script([answer("ok")]))
    sdk = SwarmSDK(
        Settings(
            memory_path=str(tmp_path / "m.db"),
            cache_path=str(tmp_path / "c.db"),
            embed_dim=32,
            memory_backend="opencl",
            recursion_limit=7,
        ),
        router_model=model,
        specialist_model=model,
        embedder=HashEmbedder(32),
        reranker=IdentityReranker(),
    )
    assert sdk._run_config("t") == {"configurable": {"thread_id": "t"}, "recursion_limit": 7}


def test_loop_maps_to_508() -> None:
    client = TestClient(create_app(_LoopingSDK()))  # type: ignore[arg-type]
    response = client.post("/v1/runs", json={"text": "hi", "thread_id": "t"})
    assert response.status_code == 508
    assert response.json() == {"detail": "handoff loop: recursion limit reached"}
```

Note: the `# type: ignore[arg-type]` above is for the duck-typed stub; if the project's checker is not run in CI, drop the comment rather than keep it unexplained (CLAUDE.md forbids unexplained ignores).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest Agents/benchmark/tests/test_recursion_limit.py -q --tb=short`
Expected: FAIL — `Settings` rejects/ignores `recursion_limit` and `_run_config` is undefined (`AttributeError`).

- [ ] **Step 3: Implement**

`settings.py`, next to `max_tokens`:

```python
    # Hard cap on graph steps per run; a handoff ping-pong stops here (spec §17.1/§17.5).
    recursion_limit: int = Field(default=50, ge=2)
```

`swarm.py`, add beside `_is_new_thread`:

```python
    def _run_config(self, thread_id: str) -> dict[str, object]:
        return {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": self.settings.recursion_limit,
        }
```
and in `_swarm._call` replace the literal config with `graph.invoke(payload, self._run_config(thread_id))`.

`http.py`: add imports `from fastapi import HTTPException` and `from langgraph.errors import GraphRecursionError`, then:

```python
    @application.post("/v1/runs", response_model=RunResult)
    async def runs(body: RunIn, request: Request) -> RunResult:
        sdk_obj: SwarmSDK = request.app.state.sdk
        try:
            return await sdk_obj.run(body.text, body.thread_id)
        except GraphRecursionError as err:
            raise HTTPException(
                status_code=508, detail="handoff loop: recursion limit reached"
            ) from err
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest Agents/benchmark/tests/test_recursion_limit.py Agents/benchmark/tests/test_api.py Agents/benchmark/tests/test_swarm.py -q --tb=short`
Expected: PASS (`test_api.py` is skipped on CPython builds without sqlite extension loading; report it as skipped, not passed).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff format src/swarm_sdk Agents/benchmark/tests/test_recursion_limit.py
uv run ruff check src Agents/benchmark/tests/test_recursion_limit.py
git add src/swarm_sdk Agents/benchmark/tests/test_recursion_limit.py
git commit -m "feat(swarm): recursion_limit setting and HTTP 508 on handoff loops" \
  -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `/healthz` liveness endpoint

**Files:**
- Modify: `src/swarm_sdk/serving/http.py`
- Test: `Agents/benchmark/tests/test_healthz.py`

**Interfaces:**
- Consumes: `create_app(sdk)` from Task 2's `http.py`.
- Produces: `GET /healthz` → `200 {"status": "ok"}`; never touches the SDK. `/v1/health` is unchanged.

- [ ] **Step 1: Write the failing test**

```python
# Agents/benchmark/tests/test_healthz.py
from fastapi.testclient import TestClient

from swarm_sdk.serving.http import create_app


class _ProvidersDownSDK:
    def provider_health(self) -> dict[str, str]:
        raise AssertionError("/healthz must not probe providers")


def test_healthz_is_independent_of_providers() -> None:
    client = TestClient(create_app(_ProvidersDownSDK()))
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run python -m pytest Agents/benchmark/tests/test_healthz.py -q --tb=short`
Expected: FAIL with `assert 404 == 200`.

- [ ] **Step 3: Implement** — in `create_app`, before `/v1/health`:

```python
    @application.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run python -m pytest Agents/benchmark/tests/test_healthz.py -q --tb=short`
Expected: PASS.

- [ ] **Step 5: Full gate, then commit**

```bash
uv run ruff format --check && uv run ruff check && uv run python -m compileall -q . && uv run python -m pytest -q --tb=short
git add src/swarm_sdk/serving/http.py Agents/benchmark/tests/test_healthz.py
git commit -m "feat(api): add /healthz liveness endpoint" \
  -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```
Expected: gate green. Pre-existing unrelated failures (e.g. `Agents/benchmark/tests/test_api.py` is already modified in the working tree, and `Websearch/tests` has a `swarm_sdk` import failure) must be reported as-is, not fixed here.

---

## Self-Review

- **Spec coverage:** §3.2 → Task 1; §17.1/§17.5 recursion limit and persistent checkpointer checklist items → Tasks 1–2; §16.2 `/healthz` → Task 3; §5.1 HTTP service already present. §3.3, §8.2, §10, §11, §13 and SSE are explicitly out of scope above with reasons.
- **Placeholders:** none; every code step has code.
- **Type consistency:** `open_checkpointer`, `_is_new_thread`, `_run_config`, `checkpoint_path`, `recursion_limit` are spelled identically in every task.
- **Review Focus:** each of the five lines has a named test (`test_restart_keeps_existing_thread`, `test_missing_parent_directory_is_created`, `test_eviction_does_not_delete_durable_checkpoints`, `test_loop_maps_to_508`, `test_healthz_is_independent_of_providers`).
- **Not verified:** I read the code and spec but ran no plan code. Unverified assumptions the executor must check at Step 1/3: the `SqliteSaver` import path and `get_tuple` behavior in the installed `langgraph-checkpoint-sqlite`; that `sdk.run` lets `GraphRecursionError` propagate (if `run` catches it, move the mapping there).
