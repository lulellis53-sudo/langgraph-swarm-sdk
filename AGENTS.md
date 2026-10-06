# Agent guidelines — LangGraph Swarm SDK

## Summary

Instructions for humans and AI assistants working in this repository. Read this first; drill into specialist docs only when your task requires them.

| Topic                                                     | What you will find                                                               |
| --------------------------------------------------------- | -------------------------------------------------------------------------------- |
| [Project overview](#topic-project-overview)               | What LangGraph Swarm SDK is; coding assistant vs swarm specialists               |
| [Repository layout](#topic-repository-layout)             | Path map; protobuf note; quick links                                             |
| [Development environment](#topic-development-environment) | Python/uv, services, quality gate, Colab/Codex, extensions                       |
| [Workflow](#topic-workflow)                               | How to change code; when stuck                                                   |
| [Benchmarks](#topic-benchmarks)                           | Task layout; SQL Pro suite                                                       |
| [Security and compliance](#topic-security-and-compliance) | Secrets; network exfiltration                                                    |
| [Git and documentation](#topic-git-and-documentation)     | Commits, README, dependencies                                                    |
| [Python Static Template](#topic-python-static-template)   | UNTOUCHABLE full scaffold (verbatim `.py`) + lite link; agent contract   |

Human-oriented overview: `[README.md](README.md)`.

---

## Topic: Project overview

### Subtopic: What this project is

**LangGraph Swarm SDK** — a Python library and runtime for parallel multi-LLM swarms: LangGraph handoffs, semantic cache, hybrid retrieval, reranking, token budgets, and optional HTTP/gRPC APIs. The design goal is **fewer tokens** and **more relevant context**, not maximal model verbosity.

### Subtopic: Two kinds of “agents”

1. **Coding assistant (you in Cursor)** — edits this repo, runs tests, opens PRs. Follow the sections below.
2. **Swarm specialists (**`Agents/`***)** — fictional roles (Coder, Tester, Security, …) with JSON output contracts for orchestrated tasks. When emulating a role, read that folder’s `[AGENTS.md](Agents/Coder/AGENTS.md)` and obey its contract. When doing general repo work, use this file and the Coder-style norms (minimal diff, tests, no secrets).

For swarm coordination: start from `[Agents/SKILLS.md](Agents/SKILLS.md)` and `[Agents/coordination.yaml](Agents/coordination.yaml)`.

---

## Topic: Repository layout

### Subtopic: Repository map

| Path                                                         | Purpose                                                                                                  |
| ------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------- |
| `[src/swarm_sdk/](src/swarm_sdk/)`                           | Library: swarm runtime, cache, memory, routing, API/gRPC                                                 |
| `[src/swarm_sdk/orchestrator/](src/swarm_sdk/orchestrator/)` | Parallel plan engine: `spawn` (goal → structured plan) + `run_plan` (LangGraph dependency waves)          |
| `[src/swarm_sdk/serving/](src/swarm_sdk/serving/)`           | HTTP/gRPC/peer serving and LangGraph Server graph factories (`swarm`, `plan`)                              |
| `[src/swarm_sdk/serving/client.py](src/swarm_sdk/serving/client.py)` | `langgraph_sdk` client; `SWARM_SERVER_URL` delegates runs to a LangGraph Server                    |
| `[langgraph.json](langgraph.json)`                           | LangGraph Server manifest mapping the `swarm` and `plan` graph ids to factory functions                   |
| `[src/swarm_sdk/pb/](src/swarm_sdk/pb/)`                     | gRPC: `swarm.proto` + generated `swarm_pb2*` stubs                                                       |
| `[Main/config/swarm.yaml](Main/config/swarm.yaml)`           | Provider registry, routes, defaults (`SWARM_*` env overrides)                                            |
| `[Main/](Main/)`                                             | Embeddings/vectorstore re-exports, YAML, Essentials                                                      |
| `[WebSearch/](WebSearch/)`                                   | Search/scrape package (`frontend/` → `midend/` → `backend/`); see `[WebSearch/README.md](WebSearch/README.md)` |
| `[Agents/](Agents/)`                                         | Specialist **swarm personas** (`AGENTS.md` + `agent.yaml` per role)                                      |
| `[Agents/coordination.yaml](Agents/coordination.yaml)`       | Task graph for multi-agent workflows                                                                     |
| `[Agents/SKILLS.md](Agents/SKILLS.md)`                       | Specialist catalog: persona → handoff node/plan-worker wiring, how to add a specialist                    |
| `[Agents/benchmark/](Agents/benchmark/)`                     | Token/retrieval/swarm benchmarks; unit/integration tests in `[Agents/benchmark/tests/](Agents/benchmark/tests/)` (incl. `[Agents/benchmark/sql_pro/](Agents/benchmark/sql_pro/)`)  |
| `[.cursor/commands/](.cursor/commands/)`                     | Cursor slash commands (e.g. `/sql-pro`)                                                                  |
| `[.cursor/AGENTS.md](.cursor/AGENTS.md)`                     | Cursor agent guidelines, folder design, modus operandi                                                   |
| `[.cursor/rules/](.cursor/rules/)`                           | Project `.mdc` rules (core, Context7-after-edit, Python, protobuf, …)                                    |
| `[.cursor/templates/](.cursor/templates/)`                   | Static scaffolds — `[python_static_template_lite.py](.cursor/templates/python_static_template_lite.py)` or full `[python_static_template.py](.cursor/templates/python_static_template.py)` |
| `[.vscode/](.vscode/)`                                       | Workspace settings + extension recommendations (Cursor/VS Code)                                          |
| `[.cursor/extensions.txt](.cursor/extensions.txt)`           | Install list mirroring recommended extensions                                                            |
| `[.codex/config.toml](.codex/config.toml)`                   | Codex IDE/CLI defaults for this repo (`file_opener = cursor`)                                            |

Edit `[src/swarm_sdk/pb/swarm.proto](src/swarm_sdk/pb/swarm.proto)` then `uv run python -m swarm_sdk.pb` to regenerate stubs. Never commit `.env`.

### Subtopic: Quick links

- Agent index: `[Agents/SKILLS.md](Agents/SKILLS.md)`
- Workspace layout: `[codeworkspace/swarm.code-workspace](codeworkspace/swarm.code-workspace)`
- Benchmarks: `[Agents/benchmark/README.md](Agents/benchmark/README.md)`
- Toolchains and CPython support: `[Toolchain.md](Toolchain.md)`
- Static template: [@.cursor/templates/python_static_template.py](.cursor/templates/python_static_template.py)

---

## Topic: Development environment

### Subtopic: Python and uv

- **Python:** `>=3.14.5`, managed with **[uv](https://docs.astral.sh/uv/)**.
- **Install:** `uv sync --extra dev` (add `--extra faiss`, `--extra faiss-gpu`, `--extra embed`, `--extra molten`, `--extra observability`, `--extra qdrant`, `--extra mem0`, `--extra jupyter` as needed).

Use `uv run …` so commands use the project virtualenv.

### Subtopic: Services

- **Run services:** `uv run swarm-api`, `uv run swarm-grpc`.
- **LangGraph Server:** `[langgraph.json](langgraph.json)` serves the `swarm` (handoff graph) and `plan` (spawn → wave engine) graphs; factories in `[src/swarm_sdk/serving/graphs.py](src/swarm_sdk/serving/graphs.py)`. Deploy with `langgraph up` (the pinned `langgraph-cli` for Python 3.14 has no in-memory `dev` server), then call it with `SWARM_SERVER_URL=http://127.0.0.1:2024` — `SwarmSDK.run` delegates to the server via `langgraph_sdk` (`swarm_sdk.serving.client`). `swarm-api`/`swarm-grpc` remain the in-process serving paths.

### Subtopic: Quality gate

Run before claiming work is done:

```bash
uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 pytest Agents/benchmark -q
uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 ruff check src Agents/benchmark Main
uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 ty check src Agents/benchmark Main
uv run python -m swarm_sdk.agents.validate
```

### Subtopic: Colab and Codex

- **Colab** (`google.colab`): open a `.ipynb` → **Select Kernel** → **Colab** → sign in with Google. Requires `uv sync --extra jupyter` for local kernels; Colab runs remotely.
- **Codex** (`openai.chatgpt`): open the Codex sidebar and sign in with ChatGPT. Repo defaults: `[.codex/config.toml](.codex/config.toml)`. For LangChain Codex routes, set `CODEX_OAUTH_TOKEN` in `.env` (see `[Main/config/model_registry.yaml](Main/config/model_registry.yaml)`).

### Subtopic: Editor extensions

- Cursor/VS Code will prompt from `[.vscode/extensions.json](.vscode/extensions.json)`, or `xargs -n1 code --install-extension < .cursor/extensions.txt`.

### Subtopic: Cursor IDE usage

Custom subagents live in `[.cursor/agents/](.cursor/agents/)` ([Cursor subagents](https://cursor.com/docs/subagents)). Slash commands live in `[.cursor/commands/](.cursor/commands/)`.

| In the Agent chat | What runs |
| ----------------- | --------- |
| `/worktree-websearch` | Slash command `[.cursor/commands/worktree-websearch.md](.cursor/commands/worktree-websearch.md)` — live research; does not patch the Hatch package |
| `/code-fixer` | Slash command `[.cursor/commands/code-fixer.md](.cursor/commands/code-fixer.md)` — apply the latest Reviewer / code-reviewer findings |
| `@code-fixer` or “send CodeFixer” | Subagent `[.cursor/agents/code-fixer.md](.cursor/agents/code-fixer.md)` (`name: code-fixer`) |
| `@WebSearch` then send Code Reviewer | Built-in `code-reviewer`; then `/code-fixer` to patch **critical** / **major** |

1. Open **Agent** (Cursor chat, Agent mode — not plain Ask).
2. Attach context with `@` (`@WebSearch`, a diff, or the review table).
3. Type `/code-fixer` or `@code-fixer`. The fixer inherits the parent model, edits claimed files, and runs focused tests. It does not commit unless you ask.

Also available in **Cursor CLI** and Cloud Agents. Swarm persona `Agents/CodeFixer/` is for plan workers, not this IDE subagent.

---

## Topic: Workflow

### Subtopic: How to change code

1. **Read first** — callers, tests, and config that touch the same behavior.
2. **Smallest correct diff** — no drive-by refactors, new abstractions, or dependencies unless the task requires them.
3. **Match conventions** — Ruff (`line-length = 100`, py314), existing naming and patterns in `src/swarm_sdk/`.
4. **Prove it** — failing test → fix → full [quality gate](#subtopic-quality-gate). Do not weaken lint/type checks without a named rule and reason.
5. **Config** — prefer `[Main/config/swarm.yaml](Main/config/swarm.yaml)` and agent manifests under `Agents/*/agent.yaml`; document new env vars in README or agent docs.
6. **Protobuf** — edit `[src/swarm_sdk/pb/swarm.proto](src/swarm_sdk/pb/swarm.proto)`, then regenerate with `uv run python -m swarm_sdk.pb`. Do not hand-edit `swarm_pb2`* stubs.
7. **New Python modules** — lite or full template (see [Python Static Template](#topic-python-static-template)); always `from __future__ import annotations` first.

### Subtopic: When stuck

- Report `blocked` with the exact command output after one reasonable retry.
- Prefer fixing the environment (uv sync, missing extra) over skipping tests.
- For provider/model behavior, read `[Main/config/swarm.yaml](Main/config/swarm.yaml)` and `[src/swarm_sdk/model_select.py](src/swarm_sdk/model_select.py)`.

---

## Topic: Benchmarks

### Subtopic: Benchmark layout

- Benchmark tasks live under `[Agents/benchmark/Tasks/](Agents/benchmark/Tasks/)`; results go to `Agents/benchmark/results/` (gitignored).

### Subtopic: SQL Pro

- SQL Pro suite: `[Agents/benchmark/sql_pro/suite.yaml](Agents/benchmark/sql_pro/suite.yaml)`, CLI `uv run python -m benchmark.sql_pro.run`, Cursor command `[.cursor/commands/sql-pro.md](.cursor/commands/sql-pro.md)`.

---

## Topic: Security and compliance

### Subtopic: Secrets

- Never commit `.env`, API keys, tokens, or credentials.
- Secrets live only in the macOS Keychain (`uv run swarm-vault set NAME`) or the gitignored, owner-only `.env` (`chmod 600`). Never add sudo, group or world read access to it.
- YAML (`agent.yaml`, `model_registry.yaml`, `coordination.yaml`, `swarm.yaml`) holds env-var **names** only (`api_key_env: ZAI_API_KEY`), never values. `test_yaml_never_holds_secret_values` enforces this; keep it green.
- Never paste secret values into issues, logs, or agent output (report path/pattern only — see `[Agents/Security/AGENTS.md](Agents/Security/AGENTS.md)`).

### Subtopic: Network

- Do not add network calls that exfiltrate repo data unless the user explicitly asks.

---

## Topic: Git and documentation

### Subtopic: Commits

- **Commits:** only when the user asks; do not force-push `main`.

### Subtopic: Documentation

- **Docs:** update `[README.md](README.md)` when behavior or install steps change; keep agent-specific rules in `Agents/*/AGENTS.md`.

### Subtopic: Dependencies

- **Dependencies:** add via `pyproject.toml` / `uv lock`; respect `[tool.uv]` constraints (e.g. `cryptography` wheel-only for Jupyter extra).

---

## Topic: Python Static Template

Runnable (full): [@.cursor/templates/python_static_template.py](.cursor/templates/python_static_template.py).  
Default for small modules (lite): [@.cursor/templates/python_static_template_lite.py](.cursor/templates/python_static_template_lite.py).

Rule: [`.cursor/rules/python-static-template.mdc`](.cursor/rules/python-static-template.mdc). Ops: [`.cursor/AGENTS.md`](.cursor/AGENTS.md).

### Subtopic: UNTOUCHABLE — full template (verbatim)

Do **not** edit the fenced block. It must stay **exactly** as `.cursor/templates/python_static_template.py`. Change the `.py` file first, then replace this block with a byte-for-byte copy. Agents must copy from here or the `.py` file; never rewrite the scaffold in place.

```python
"""Python Static Template — Swarm (PEP 810–ready).

Agent contract (coding assistants):
  Read callers, tests, and config before editing.
  One failed attempt → analyse root cause → one deliberate fix (no retry loops).
  Profile before optimizing hot paths; measure before/after (Optimizer norms).
  Delete unused role sections when copying; no import-time side effects.
  Parallel swarm steps: disjoint ``files`` per sibling agent; cap via ``CoworkRole``.
  In ``src/swarm_sdk/``: use ``swarm_sdk.runtime.concurrency`` for caps.

Copy this skeleton when starting a new module under ``src/swarm_sdk/``.
Delete unused role sections. Keep roles grouped; do not interleave unrelated helpers.

Layout:

1. Module docstring, then **always** ``from __future__ import annotations`` (first statement)
2. Stdlib / third-party / local imports (no import-time side effects)
3. ``@wrappers`` — reusable decorators
4. Role classes — ``Type``, ``Hint``, ``Vect``, ``Math``, ``Db``, ``Batch``, ``Cowork``, …
5. Role functions — same order as classes (``loop_*`` aliases for ``batch_*``)
6. ``__all__`` + optional ``main`` under ``__main__`` only

PEP 810 (Explicit lazy imports, Python 3.15+): defer heavy deps; ``TYPE_CHECKING`` for types.
PEP 703 free-threaded 3.14: ``CoworkRole`` / ``swarm_sdk.runtime.concurrency.parallel_cap``.

Canonical source: ``.cursor/templates/python_static_template.py``.
Lite: ``python_static_template_lite.py``.
Ops: root ``AGENTS.md`` → Topic: Python Static Template. Do not import this file from runtime code.
"""

# ALWAYS: first statement after the module docstring — before any other import.
from __future__ import annotations

import functools
import os
import sys
import time
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Annotated, Any, ParamSpec, Protocol, TypeVar

if TYPE_CHECKING:
    pass

# =============================================================================
# Python Static Template
# =============================================================================

P = ParamSpec("P")
R = TypeVar("R")
T = TypeVar("T")

type Vec = Sequence[float]
type Matrix = Sequence[Sequence[float]]
type RowId = Annotated[int, "primary key"]

_DEFAULT_TRANSIENT: tuple[type[BaseException], ...] = (
    TimeoutError,
    OSError,
    ConnectionError,
)


class wrappers:
    """Static namespace for decorator factories. Prefer `@wrappers.name`."""

    @staticmethod
    def timed(fn: Callable[P, R]) -> Callable[P, R]:
        """Record wall time only when ``SWARM_PROFILE`` is set (not for hot paths)."""
        if not os.environ.get("SWARM_PROFILE"):
            return fn

        @functools.wraps(fn)
        def _inner(*args: P.args, **kwargs: P.kwargs) -> R:
            start = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                _ = time.perf_counter() - start

        return _inner

    @staticmethod
    def logged(fn: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(fn)
        def _inner(*args: P.args, **kwargs: P.kwargs) -> R:
            return fn(*args, **kwargs)

        return _inner

    @staticmethod
    def retry_transient(
        times: int = 2,
        on: tuple[type[BaseException], ...] = _DEFAULT_TRANSIENT,
    ) -> Callable[[Callable[P, R]], Callable[P, R]]:
        """Retry only on transient errors — never on validation or logic bugs."""

        def _decorate(fn: Callable[P, R]) -> Callable[P, R]:
            @functools.wraps(fn)
            def _inner(*args: P.args, **kwargs: P.kwargs) -> R:
                last: BaseException | None = None
                attempts = max(times, 1)
                for _ in range(attempts):
                    try:
                        return fn(*args, **kwargs)
                    except on as exc:
                        last = exc
                if last is not None:
                    raise last
                return fn(*args, **kwargs)

            return _inner

        return _decorate

    @staticmethod
    def retry(times: int = 1) -> Callable[[Callable[P, R]], Callable[P, R]]:
        """Alias for :meth:`retry_transient` (prefer ``retry_transient`` explicitly)."""
        return wrappers.retry_transient(times=times)


class TypeRole:
    class SupportsClose(Protocol):
        def close(self) -> None: ...

    @staticmethod
    def ensure_str(value: object) -> str:
        if not isinstance(value, str):
            raise TypeError(f"expected str, got {type(value).__name__}")
        return value


@dataclass(frozen=True, slots=True)
class HintRole:
    name: str
    description: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

    def as_annotated(self) -> Any:
        return Annotated[str, self]


@dataclass(slots=True)
class VectRole:
    dim: int

    def zeros(self) -> list[float]:
        return [0.0] * self.dim

    def dot(self, a: Vec, b: Vec) -> float:
        if len(a) != len(b):
            raise ValueError("vector length mismatch")
        return sum(x * y for x, y in zip(a, b, strict=True))


class MathRole:
    @staticmethod
    def clamp(x: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, x))

    @staticmethod
    def mean(xs: Iterable[float]) -> float:
        total = 0.0
        n = 0
        for x in xs:
            total += x
            n += 1
        if n == 0:
            raise ValueError("empty sequence")
        return total / n


@dataclass(slots=True)
class DbRole:
    path: str
    _open: bool = False

    def connect(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    @wrappers.logged
    def get(self, key: str) -> bytes | None:
        if not self._open:
            raise RuntimeError("db not connected")
        _ = key
        return None


class CoworkRole:
    """Sketch — in ``src/swarm_sdk`` import ``swarm_sdk.runtime.concurrency`` instead."""

    @staticmethod
    def gil_enabled() -> bool:
        try:
            return sys._is_gil_enabled()
        except AttributeError:
            return True

    @staticmethod
    def parallel_cap() -> int:
        return 8 if CoworkRole.gil_enabled() else 32


class BatchRole:
    """Bounded batch / async helpers (not unbounded loops)."""

    @staticmethod
    async def gather_limited[T](
        coros: Sequence[Awaitable[T]],
        *,
        limit: int | None = None,
    ) -> list[T]:
        import asyncio

        cap = limit if limit is not None else CoworkRole.parallel_cap()
        sem = asyncio.Semaphore(max(cap, 1))
        results: list[T] = []

        async def _one(aw: Awaitable[T]) -> None:
            async with sem:
                results.append(await aw)

        async with asyncio.TaskGroup() as tg:
            for aw in coros:
                tg.create_task(_one(aw))
        return results


LoopRole = BatchRole


def type_is_mapping(value: object) -> bool:
    return isinstance(value, dict)


def hint_tag(*tags: str) -> HintRole:
    return HintRole(name="tag", tags=tags)


@wrappers.timed
def vect_l2(a: Vec, b: Vec) -> float:
    if len(a) != len(b):
        raise ValueError("vector length mismatch")
    return sum((x - y) ** 2 for x, y in zip(a, b, strict=True)) ** 0.5


def math_safe_div(num: float, den: float, default: float = 0.0) -> float:
    if den == 0.0:
        return default
    return num / den


def db_uri(path: str, *, read_only: bool = False) -> str:
    mode = "mode=ro" if read_only else "mode=rwc"
    return f"file:{path}?{mode}"


def batch_chunked[T](items: Sequence[T], size: int) -> list[Sequence[T]]:
    if size < 1:
        raise ValueError("size must be >= 1")
    return [items[i : i + size] for i in range(0, len(items), size)]


def loop_chunked[T](items: Sequence[T], size: int) -> list[Sequence[T]]:
    return batch_chunked(items, size)


def cowork_gil_enabled() -> bool:
    try:
        from swarm_sdk.runtime.concurrency import gil_enabled as sdk_gil

        return sdk_gil()
    except ImportError:
        return CoworkRole.gil_enabled()


def cowork_parallel_cap() -> int:
    try:
        from swarm_sdk.runtime.concurrency import parallel_cap as sdk_cap

        return sdk_cap()
    except ImportError:
        return CoworkRole.parallel_cap()


__all__ = [
    "wrappers",
    "TypeRole",
    "HintRole",
    "VectRole",
    "MathRole",
    "DbRole",
    "BatchRole",
    "LoopRole",
    "CoworkRole",
    "type_is_mapping",
    "hint_tag",
    "vect_l2",
    "math_safe_div",
    "db_uri",
    "batch_chunked",
    "loop_chunked",
    "cowork_gil_enabled",
    "cowork_parallel_cap",
]


def main() -> int:
    """Smoke + Optimizer-style cap check (profile hot paths with ``SWARM_PROFILE=1``)."""
    v = VectRole(dim=3)
    assert MathRole.clamp(v.dot([1, 0, 0], [1, 0, 0]), 0.0, 1.0) == 1.0
    assert loop_chunked([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]
    cap = cowork_parallel_cap()
    assert cap in (8, 32)
    from swarm_sdk.runtime.concurrency import parallel_cap as sdk_cap

    assert cap == sdk_cap()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

### Subtopic: Mandatory first import

Module docstring, then immediately:

```python
from __future__ import annotations
```

### Subtopic: Agent contract

- Read callers, tests, and config before editing.
- One failed attempt → analyse → one deliberate fix (no blind retries).
- Profile before optimizing; use `SWARM_PROFILE=1` only for `@wrappers.timed` on non-hot paths.
- Parallel swarm steps: disjoint `files` per sibling; cap via `cowork_parallel_cap()` / `swarm_sdk.runtime.concurrency.parallel_cap`.
- Delete unused role sections when copying; no import-time side effects.

### Subtopic: When to use

| Scaffold | Use when |
| -------- | -------- |
| **lite** | New small module (types + cowork cap only) |
| **full** | Needs vect/math/db/batch roles |

Do **not** import template files from runtime package code — copy and trim.

### Subtopic: Roles at a glance (full template)

| Role | Class | Functions | Concern |
| ------ | -------- | ----------- | --------- |
| type | `TypeRole` | `type_*` | Protocols, narrowers |
| hint | `HintRole` | `hint_*` | Annotations / metadata |
| vect | `VectRole` | `vect_*` | Vectors / embeddings math |
| math | `MathRole` | `math_*` | Scalar / reductions (no I/O) |
| db | `DbRole` | `db_*` | Store / connection façade |
| batch | `BatchRole` | `batch_*`, `loop_*` | Bounded batch/async (`LoopRole` = alias) |
| cowork | `CoworkRole` | `cowork_*` | PEP 703 caps; runtime: `swarm_sdk.runtime.concurrency` |

### Subtopic: Wrappers

- `@wrappers.retry_transient(times=2, on=(TimeoutError, OSError, ConnectionError))` — not for logic bugs.
- `@wrappers.timed` — active only when `SWARM_PROFILE` is set.

### Subtopic: Smoke check

```bash
uv run python .cursor/templates/python_static_template.py
uv run python .cursor/templates/python_static_template_lite.py
```
