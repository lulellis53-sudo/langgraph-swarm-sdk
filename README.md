# LangGraph Swarm SDK

Parallel multi-LLM swarm on [LangGraph Swarm](https://github.com/langchain-ai/langgraph-swarm-py): specialist handoffs, asyncio fan-out, int8 memory, a cross-encoder reranker, a tokenizer budget, and a semantic cache. The point of the cache, reranker, and budget is to send fewer tokens and keep the tokens that remain relevant.

## Requirements

- Python `>=3.14.5` (`uv python install 3.14.5`; see `.python-version`)
- [uv](https://docs.astral.sh/uv/)

```bash
uv sync --python 3.14.5 --extra dev --extra faiss --extra qdrant
```

FastEmbed is the default embedder and reranker. Current `onnxruntime` wheels do not include macOS x86_64, so that extra is skipped on Intel Macs. Tests inject a local embedder and do not download models.

## Run

```bash
uv run swarm-api
uv run swarm-grpc
```

`POST /v1/runs` with `{"text": "...", "thread_id": "t1"}`. `GET /v1/health`. gRPC `SwarmService.Run` and `SwarmService.Recall` call the same core.

Predefined providers and routes live in [`config/swarm.yaml`](config/swarm.yaml). Per-agent roles, models, and tasks live in [`Agents/{Name}/agent.yaml`](Agents/Tester/agent.yaml) (see [`Agents/SKILLS.md`](Agents/SKILLS.md)). `SWARM_*` env vars override file defaults. Open [`codeworkspace/swarm.code-workspace`](codeworkspace/swarm.code-workspace) for a multi-root editor layout.

## Token path

1. Exact SHA-256 cache, then a cosine semantic cache (default threshold `0.97`).
2. Router on `think_level: low` with provider fallback and circuit breakers (`GET /v1/health` shows breaker state).
3. Think-level token caps, then tokenizer budget (system prompt, memories, newest turns; tool text capped).
4. Hybrid dense + BM25 recall (RRF), dedupe, rerank; only top-k snippets injected. sqlite-vec int8 + optional FTS5 side index.
5. Near-duplicate memories dropped before the prompt.
6. Parallel fan-out with bounded concurrency and JSON briefs; LangGraph handoffs for sequential specialist work.

HTTP peers use `httpx2` with HTTP/2 (`h2`). `aiohttp` and `requests` are the other clients.

## Checks

```bash
uv sync --python 3.14.5 --extra dev
uv run pytest tests benchmark -q
uv run ruff check src tests benchmark
uv run ty check src tests benchmark
uv run python -m swarm_sdk.agents.validate
```

---

# Codebase rules

Contributor conventions for this repository. On case-insensitive filesystems, `README.MD` and `README.md` refer to this same file.

## Layout

| Path | Role |
|------|------|
| `src/swarm_sdk/` | Library code (package root) |
| `tests/` | Unit tests; fakes in `tests/fakes.py` |
| `benchmark/` | Task harness + integration-style benchmarks (no live API keys in CI) |
| `config/swarm.yaml` | Runtime providers, models, hybrid search, parallelism |
| `Agents/{Name}/` | `agent.yaml` manifest + `AGENTS.md` contract |
| `Agents/coordination.yaml` | Swarm tasks and manifest links |
| `codeworkspace/` | Multi-root VS Code/Cursor workspace (no path moves) |

Do not move `src/` under `codeworkspace/` — packaging and CI assume repo-root `pyproject.toml`.

## Toolchain

- **Python:** `>=3.14.5` (pin with `.python-version` / `uv python pin 3.14.5`). Use **3.14.5** for sqlite-vec extension loading; 3.14.7+ builds may lack `enable_load_extension`.
- **Package manager:** [uv](https://docs.astral.sh/uv/) — `uv sync --extra dev`
- **Lint:** `ruff check src tests benchmark` (`target-version = py314`, line length 100)
- **Types:** `ty check src tests benchmark`
- **Tests:** `pytest tests benchmark -q`
- **Agents:** `python -m swarm_sdk.agents.validate`

## Python file baseline

Every new `.py` file under `src/`, `tests/`, and `benchmark/`:

1. **Module docstring** — one sentence on purpose (omit only for `__init__.py` re-exports if empty).
2. **`from __future__ import annotations`** — first statement after the docstring (PEP 563 deferred annotations; required project-wide).
3. **Imports** — stdlib → third party → `swarm_sdk` / local; let Ruff (`I`) sort.
4. **Typing** — prefer `X | Y`, `list[str]`, `Protocol`, `TypedDict` sparingly; Pydantic `BaseModel` for config and IO boundaries.
5. **No secrets** — API keys via env / `config/swarm.yaml` `*_env` fields only.

## Static module template (classes + decorators)

Use this shape for services, stores, and agents. Match existing modules (`resilience.py`, `runtime.py`, `swarm.py`).

```python
"""Short description of this module."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Final, Protocol

from pydantic import BaseModel, Field

_DEFAULT_TIMEOUT: Final[float] = 30.0


class WorkerConfig(BaseModel):
    """Validated config loaded from YAML or env."""

    max_workers: int = Field(default=8, ge=1)
    timeout_s: float = Field(default=_DEFAULT_TIMEOUT, gt=0)


class Backend(Protocol):
    def fetch(self, key: str) -> str: ...


class WorkerService:
    """Owns lifecycle and concurrency boundaries for one subsystem."""

    def __init__(self, config: WorkerConfig, backend: Backend) -> None:
        self._config = config
        self._backend = backend
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    @classmethod
    def from_settings(cls, config: WorkerConfig) -> WorkerService:
        return cls(config, backend=_DefaultBackend())

    @staticmethod
    def _normalize_key(key: str) -> str:
        return key.strip().lower()

    async def run(self, key: str) -> str:
        if self._closed:
            raise RuntimeError("WorkerService is closed")
        normalized = self._normalize_key(key)
        # Prefer swarm_sdk.runtime.offload for blocking work (shared thread pool).
        return await asyncio.to_thread(self._backend.fetch, normalized)

    async def run_many(self, keys: list[str]) -> list[str]:
        return list(await asyncio.gather(*(self.run(k) for k in keys)))

    def close(self) -> None:
        self._closed = True


class _DefaultBackend:
    def fetch(self, key: str) -> str:
        return key
```

**Decorators in this repo**

| Decorator | Use |
|-----------|-----|
| `@property` | Cheap derived state (`CircuitBreaker.state`, flags) |
| `@classmethod` | Alternate constructors (`SwarmSDK.from_settings`, validators) |
| `@staticmethod` | Pure helpers that do not need `self` |
| `@pytest.mark.asyncio` | Async tests (`asyncio_mode = auto` in pytest) |

Prefer **plain functions** for one-off helpers; add a class when there is mutable state, lifecycle, or a clear boundary. Use **`Protocol`** for duck-typed dependencies (memory stores, rerankers, embedders).

## Free-threaded CPython (PEP 703 / PEP 779)

This project targets **3.14+**, where [PEP 779](https://peps.python.org/pep-0799/) documents supported free-threading and [PEP 703](https://peps.python.org/pep-0703/) describes the optional GIL-disabled build. Code must remain correct **with or without** the GIL.

| Rule | Rationale |
|------|-----------|
| **Do not rely on the GIL** for mutual exclusion | Another thread can run Python code concurrently in free-threaded builds |
| **Protect shared mutable state** with `threading.Lock` / `asyncio.Lock` | See `SqliteVecStore._lock` |
| **Prefer asyncio** for fan-out; use `runtime.offload()` for blocking CPU/IO | Keeps LangGraph and sqlite off the event loop |
| **Document thread-safety** on types that are not safe | e.g. `CircuitBreaker` — one instance per provider / task family |
| **Immutable config** after load | Pydantic models and `Settings` are read-mostly; avoid mutating at runtime |
| **Avoid `threading.local` for correctness** unless documented | Prefer explicit context passed through `run()` |

Optional local free-threaded interpreter (when installed):

```bash
# Example; exact build flags depend on your CPython install
PYTHON_GIL=0 uv run pytest tests -q
```

If a module is only safe under the GIL, say so in its docstring and add a lock before enabling free-threaded CI.

## Asyncio

Concurrency in this repo is **async-first**. Sync code is allowed only at the edges (LangGraph `invoke`, sqlite, embedders) and must not block the event loop.

| Pattern | Where | Rule |
|---------|--------|------|
| `async def` entrypoints | `SwarmSDK.run`, FastAPI, gRPC servicer | Return awaitables; no hidden blocking |
| `await offload(fn, *args)` | `runtime.py` | Blocking CPU/IO off the loop (shared pool) |
| `await bounded_gather(...)` | `parallel.py`, `model_select.py` | Cap fan-out via `parallelism.max_concurrency` |
| `asyncio.gather` | Small fixed fan-in inside a service | OK when task count is bounded |
| `install_uvloop()` | API/gRPC `main()` | uvloop policy on non-Windows |
| `@pytest.mark.asyncio` | `tests/`, `benchmark/` | `asyncio_mode = auto` in `pyproject.toml` |

**Do**

- Use `async with asyncio.Lock()` when async tasks share mutable state.
- Propagate `asyncio.CancelledError` (do not swallow cancellation).
- Time out external calls at the transport layer when adding new clients.

**Do not**

- Call blocking sqlite, file, or sync LLM APIs directly inside `async def` without `offload`.
- Use `asyncio.run()` inside library code (only CLI / servicer top level).
- Create unbounded `create_task` loops without semaphores or `bounded_gather`.

Minimal async module shape:

```python
"""Async-facing helper."""

from __future__ import annotations

from swarm_sdk.runtime import offload


async def recall_and_pack(query: str, store: object) -> str:
    hits = await offload(_search_sync, store, query)
    return _format(hits)


def _search_sync(store: object, query: str) -> list[str]:
    ...


def _format(hits: list[str]) -> str:
    return "\n".join(hits)
```

Servers call `runtime.install_uvloop()` before `uvicorn.run` / serving gRPC.

## Config and agents

- Load [`config/swarm.yaml`](config/swarm.yaml) via `yaml_config.load_swarm_config()` / `load_merged_settings()`; env `SWARM_*` overrides.
- Quote YAML think levels (`"off"`, `"low"`) — bare `off` becomes boolean `false`.
- New agent roles: `Agents/{Name}/agent.yaml` + update `Agents/coordination.yaml` + run `swarm_sdk.agents.validate`.

## Commits and scope

- Smallest correct diff; match surrounding naming and patterns.
- Comments only for non-obvious invariants (thread-safety, token budgets, breaker state).
- Do not commit `.env`, keys, or `benchmark/results/` artifacts.

## Quick checklist (new module)

- [ ] Module docstring
- [ ] `from __future__ import annotations`
- [ ] Public I/O is `async def` or explicitly documented sync
- [ ] Types on public functions and methods
- [ ] Pydantic or `Settings` for external input
- [ ] Thread-safety note if mutable shared state exists
- [ ] Tests or benchmark task when behavior is user-visible
- [ ] `ruff` + `ty` clean
