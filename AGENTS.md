# Agent guidelines — LangGraph Swarm SDK

## Summary

Instructions for humans and AI assistants working in this repository. Read this first; drill into specialist docs only when your task requires them.

| Topic | What you will find |
| ----- | ------------------ |
| [Project overview](#topic-project-overview) | What LangGraph Swarm SDK is; coding assistant vs swarm specialists |
| [Repository layout](#topic-repository-layout) | Path map; protobuf note; quick links |
| [Development environment](#topic-development-environment) | Python/uv, services, quality gate, Colab/Codex, extensions |
| [Workflow](#topic-workflow) | How to change code; when stuck |
| [Benchmarks](#topic-benchmarks) | Task layout; SQL Pro suite |
| [Security and compliance](#topic-security-and-compliance) | Secrets; network exfiltration |
| [Git and documentation](#topic-git-and-documentation) | Commits, README, dependencies |
| [Python Static Template](#topic-python-static-template) | Full scaffold source (merged with `.cursor/templates/python_static_template.py`) |

Human-oriented overview: [`README.md`](README.md).

---

## Topic: Project overview

### Subtopic: What this project is

**LangGraph Swarm SDK** — a Python library and runtime for parallel multi-LLM swarms: LangGraph handoffs, semantic cache, hybrid retrieval, reranking, token budgets, and optional HTTP/gRPC APIs. The design goal is **fewer tokens** and **more relevant context**, not maximal model verbosity.

### Subtopic: Two kinds of “agents”

1. **Coding assistant (you in Cursor)** — edits this repo, runs tests, opens PRs. Follow the sections below.
2. **Swarm specialists (`Agents/*`)** — fictional roles (Coder, Tester, Security, …) with JSON output contracts for orchestrated tasks. When emulating a role, read that folder’s [`AGENTS.md`](Agents/Coder/AGENTS.md) and obey its contract. When doing general repo work, use this file and the Coder-style norms (minimal diff, tests, no secrets).

For swarm coordination: start from [`Agents/SKILLS.md`](Agents/SKILLS.md) and [`Agents/coordination.yaml`](Agents/coordination.yaml).

---

## Topic: Repository layout

### Subtopic: Repository map

| Path | Purpose |
| ------ | --------- |
| [`src/swarm_sdk/`](src/swarm_sdk/) | Library: swarm runtime, cache, memory, routing, API/gRPC |
| [`src/swarm_sdk/orchestrator/`](src/swarm_sdk/orchestrator/) | Parallel plan engine: `spawn` (goal → JSON plan) + `run_plan` (LangGraph dependency waves) |
| [`src/swarm_sdk/pb/`](src/swarm_sdk/pb/) | gRPC: `swarm.proto` + generated `swarm_pb2*` stubs |
| [`config/swarm.yaml`](config/swarm.yaml) | Provider registry, routes, defaults (`SWARM_*` env overrides) |
| [`Agents/`](Agents/) | Specialist **swarm personas** (`AGENTS.md` + `agent.yaml` per role) |
| [`Agents/coordination.yaml`](Agents/coordination.yaml) | Task graph for multi-agent workflows |
| [`Agents/SKILLS.md`](Agents/SKILLS.md) | Index of swarm agents and how to run them |
| [`tests/`](tests/) | Unit and integration tests |
| [`benchmark/`](benchmark/) | Token/retrieval/swarm benchmarks (incl. [`benchmark/sql_pro/`](benchmark/sql_pro/)) |
| [`.cursor/commands/`](.cursor/commands/) | Cursor slash commands (e.g. `/sql-pro`) |
| [`.cursor/AGENTS.md`](.cursor/AGENTS.md) | Cursor agent guidelines, folder design, modus operandi |
| [`.cursor/rules/`](.cursor/rules/) | Project `.mdc` rules (core, Context7-after-edit, Python, protobuf, …) |
| [`.cursor/templates/`](.cursor/templates/) | Static scaffolds — start with [`python_static_template.py`](.cursor/templates/python_static_template.py) |
| [`.vscode/`](.vscode/) | Workspace settings + extension recommendations (Cursor/VS Code) |
| [`.cursor/extensions.txt`](.cursor/extensions.txt) | Install list mirroring recommended extensions |
| [`.codex/config.toml`](.codex/config.toml) | Codex IDE/CLI defaults for this repo (`file_opener = cursor`) |

Edit [`src/swarm_sdk/pb/swarm.proto`](src/swarm_sdk/pb/swarm.proto) then `uv run python -m swarm_sdk.pb` to regenerate stubs. Never commit `.env`.

### Subtopic: Quick links

- Agent index: [`Agents/SKILLS.md`](Agents/SKILLS.md)
- Workspace layout: [`codeworkspace/swarm.code-workspace`](codeworkspace/swarm.code-workspace)
- Benchmarks: [`benchmark/README.md`](benchmark/README.md)
- Static template: [@.cursor/templates/python_static_template.py](.cursor/templates/python_static_template.py)

---

## Topic: Development environment

### Subtopic: Python and uv

- **Python:** `>=3.14.5`, managed with **[uv](https://docs.astral.sh/uv/)**.
- **Install:** `uv sync --extra dev` (add `--extra faiss`, `--extra faiss-gpu`, `--extra embed`, `--extra molten`, `--extra observability`, `--extra qdrant`, `--extra mem0`, `--extra jupyter` as needed).

Use `uv run …` so commands use the project virtualenv.

### Subtopic: Services

- **Run services:** `uv run swarm-api`, `uv run swarm-grpc`.

### Subtopic: Quality gate

Run before claiming work is done:

```bash
uv run --extra dev pytest tests benchmark -q
uv run --extra dev ruff check src tests benchmark
uv run --extra dev ty check src tests benchmark
uv run python -m swarm_sdk.agents.validate
```

### Subtopic: Colab and Codex

- **Colab** (`google.colab`): open a `.ipynb` → **Select Kernel** → **Colab** → sign in with Google. Requires `uv sync --extra jupyter` for local kernels; Colab runs remotely.
- **Codex** (`openai.chatgpt`): open the Codex sidebar and sign in with ChatGPT. Repo defaults: [`.codex/config.toml`](.codex/config.toml). For LangChain Codex routes, set `CODEX_OAUTH_TOKEN` in `.env` (see [`config/model_registry.yaml`](config/model_registry.yaml)).

### Subtopic: Editor extensions

- Cursor/VS Code will prompt from [`.vscode/extensions.json`](.vscode/extensions.json), or `xargs -n1 code --install-extension < .cursor/extensions.txt`.

---

## Topic: Workflow

### Subtopic: How to change code

1. **Read first** — callers, tests, and config that touch the same behavior.
2. **Smallest correct diff** — no drive-by refactors, new abstractions, or dependencies unless the task requires them.
3. **Match conventions** — Ruff (`line-length = 100`, py314), existing naming and patterns in `src/swarm_sdk/`.
4. **Prove it** — failing test → fix → full [quality gate](#subtopic-quality-gate). Do not weaken lint/type checks without a named rule and reason.
5. **Config** — prefer [`config/swarm.yaml`](config/swarm.yaml) and agent manifests under `Agents/*/agent.yaml`; document new env vars in README or agent docs.
6. **Protobuf** — edit [`src/swarm_sdk/pb/swarm.proto`](src/swarm_sdk/pb/swarm.proto), then regenerate with `uv run python -m swarm_sdk.pb`. Do not hand-edit `swarm_pb2*` stubs.
7. **New Python modules** — copy from [@.cursor/templates/python_static_template.py](.cursor/templates/python_static_template.py); see [Python Static Template](#topic-python-static-template).

### Subtopic: When stuck

- Report `blocked` with the exact command output after one reasonable retry.
- Prefer fixing the environment (uv sync, missing extra) over skipping tests.
- For provider/model behavior, read [`config/swarm.yaml`](config/swarm.yaml) and [`src/swarm_sdk/model_select.py`](src/swarm_sdk/model_select.py).

---

## Topic: Benchmarks

### Subtopic: Benchmark layout

- Benchmark tasks live under [`benchmark/Tasks/`](benchmark/Tasks/); results go to `benchmark/results/` (gitignored).

### Subtopic: SQL Pro

- SQL Pro suite: [`benchmark/sql_pro/suite.yaml`](benchmark/sql_pro/suite.yaml), CLI `uv run python -m benchmark.sql_pro.run`, Cursor command [`.cursor/commands/sql-pro.md`](.cursor/commands/sql-pro.md).

---

## Topic: Security and compliance

### Subtopic: Secrets

- Never commit `.env`, API keys, tokens, or credentials.
- Never paste secret values into issues, logs, or agent output (report path/pattern only — see [`Agents/Security/AGENTS.md`](Agents/Security/AGENTS.md)).

### Subtopic: Network

- Do not add network calls that exfiltrate repo data unless the user explicitly asks.

---

## Topic: Git and documentation

### Subtopic: Commits

- **Commits:** only when the user asks; do not force-push `main`.

### Subtopic: Documentation

- **Docs:** update [`README.md`](README.md) when behavior or install steps change; keep agent-specific rules in `Agents/*/AGENTS.md`.

### Subtopic: Dependencies

- **Dependencies:** add via `pyproject.toml` / `uv lock`; respect `[tool.uv]` constraints (e.g. `cryptography` wheel-only for Jupyter extra).

---

## Topic: Python Static Template

Runnable file (Cursor `@` attach): [@.cursor/templates/python_static_template.py](.cursor/templates/python_static_template.py). **This topic merges that file in full** — keep the block below and the `.py` file in sync when you change the scaffold.

Rule: [`.cursor/rules/python-static-template.mdc`](.cursor/rules/python-static-template.mdc). Ops: [`.cursor/AGENTS.md`](.cursor/AGENTS.md). Every `Agents/*/AGENTS.md` links here too.

### Subtopic: When to use

- Creating a **new** module under `src/swarm_sdk/` (not drive-by edits).
- Copy from the merged source below (or the `.py` file), rename it, **delete unused role sections**, keep remaining roles contiguous.
- Do **not** import the template from runtime package code.

### Subtopic: Roles at a glance

| Role | Class | Functions | Concern |
| ------ | -------- | ----------- | --------- |
| type | `TypeRole` | `type_*` | Protocols, narrowers |
| hint | `HintRole` | `hint_*` | Annotations / metadata |
| vect | `VectRole` | `vect_*` | Vectors / embeddings math |
| math | `MathRole` | `math_*` | Scalar / reductions (no I/O) |
| db | `DbRole` | `db_*` | Store / connection façade |
| loop | `LoopRole` | `loop_*` | Async / batch iteration |
| cowork | `CoworkRole` | `cowork_*` | Free-threading caps for parallel agents (PEP 703) |

### Subtopic: Mandatory first import

Every new module under `src/swarm_sdk/`: **module docstring**, then immediately (before any other import or code):

```python
from __future__ import annotations
```

### Subtopic: Free-threading and agent cowork

- **PEP 703** free-threaded Python 3.14: `CoworkRole.parallel_cap()` returns `8` (GIL) or `32` (no GIL), matching [`swarm_sdk/execution/executor.py`](src/swarm_sdk/execution/executor.py).
- Parallel swarm steps: cap concurrency with `LoopRole.gather_limited(..., limit=None)`; sibling agents claim **disjoint `files`** per orchestrator wave (see root [`README.md`](README.md)).
- Role helpers: `cowork_gil_enabled()`, `cowork_parallel_cap()`.

### Subtopic: Full template source

Section comments use `# Python Static Template — …` (type aliases, wrappers, role classes, role functions, public surface).

```python
"""Python Static Template — Swarm (PEP 810–ready).

Copy this skeleton when starting a new module under ``src/swarm_sdk/``.
Delete unused role sections. Keep roles grouped; do not interleave unrelated helpers.

Layout:

1. Module docstring, then **always** ``from __future__ import annotations`` (first statement)
2. Stdlib / third-party / local imports (no import-time side effects)
3. ``@wrappers`` — reusable decorators
4. Role classes — ``Type``, ``Hint``, ``Vect``, ``Math``, ``Db``, ``Loop``, …
5. Role functions — same order as classes
6. ``__all__`` + optional ``main`` under ``__main__`` only

PEP 810 (Explicit lazy imports, Python 3.15+): keep this module free of
import-time side effects so it stays ``lazy import``–eligible. On 3.14,
defer heavy optional deps inside the functions that need them; use
``TYPE_CHECKING`` for type-only imports.

Free-threaded Python 3.14 (PEP 703): use :class:`CoworkRole` caps so parallel swarm
agents (disjoint files per wave) scale on no-GIL builds without oversubscribing
on GIL builds. Matches ``swarm_sdk.execution.executor`` pool sizing.

Canonical copy also lives in root ``AGENTS.md`` → Topic: Python Static Template.
Do not import this file from runtime package code — copy and trim.
"""

# ALWAYS: first statement after the module docstring — before any other import.
from __future__ import annotations

import functools
import sys
import time
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Annotated, Any, ParamSpec, Protocol, TypeVar

if TYPE_CHECKING:
    # Type-only imports stay here (PEP 649/749 + PEP 810–friendly).
    pass

# =============================================================================
# Python Static Template
# =============================================================================
# Topic map (root ``AGENTS.md`` → Topic: Python Static Template):
#   Subtopic: type aliases & typevars
#   Subtopic: wrappers
#   Subtopic: role classes (Type → Hint → Vect → Math → Db → Loop → Cowork)
#   Subtopic: role functions (same order)
#   Subtopic: free-threading & agent cowork (CoworkRole / cowork_*)
#   Subtopic: public surface (+ ``main`` smoke under ``__main__`` only)
# =============================================================================

# --- Python Static Template — type aliases & typevars -----------------------
# Python 3.12+ ``type`` statement; shared by roles
# -----------------------------------------------------------------------------

P = ParamSpec("P")
R = TypeVar("R")
T = TypeVar("T")

type Vec = Sequence[float]
type Matrix = Sequence[Sequence[float]]
type RowId = Annotated[int, "primary key"]


# --- Python Static Template — wrappers --------------------------------------
# Decorators: @wrappers.timed, @wrappers.logged, @wrappers.retry(n)
# -----------------------------------------------------------------------------


class wrappers:
    """Static namespace for decorator factories. Prefer `@wrappers.name`."""

    @staticmethod
    def timed(fn: Callable[P, R]) -> Callable[P, R]:
        """Record wall time on ``fn.__name__`` (no I/O at decoration time)."""

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
        """Preserve signature; hook for structured logging later."""

        @functools.wraps(fn)
        def _inner(*args: P.args, **kwargs: P.kwargs) -> R:
            return fn(*args, **kwargs)

        return _inner

    @staticmethod
    def retry(times: int = 1) -> Callable[[Callable[P, R]], Callable[P, R]]:
        """Retry sync call ``times`` times on any Exception."""

        def _decorate(fn: Callable[P, R]) -> Callable[P, R]:
            @functools.wraps(fn)
            def _inner(*args: P.args, **kwargs: P.kwargs) -> R:
                last: Exception | None = None
                for _ in range(max(times, 1)):
                    try:
                        return fn(*args, **kwargs)
                    except Exception as exc:  # noqa: BLE001 — template boundary
                        last = exc
                assert last is not None
                raise last

            return _inner

        return _decorate


# --- Python Static Template — role classes ----------------------------------
# One concern per class; keep methods thin
# -----------------------------------------------------------------------------


# --- type -------------------------------------------------------------------


class TypeRole:
    """Structural typing helpers (Protocols, narrowers)."""

    class SupportsClose(Protocol):
        def close(self) -> None: ...

    @staticmethod
    def ensure_str(value: object) -> str:
        if not isinstance(value, str):
            raise TypeError(f"expected str, got {type(value).__name__}")
        return value


# --- hint -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HintRole:
    """Annotation / metadata carriers for APIs and schemas."""

    name: str
    description: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

    def as_annotated(self) -> Any:
        return Annotated[str, self]


# --- vect -------------------------------------------------------------------


@dataclass(slots=True)
class VectRole:
    """Vector ops surface (CPU path; swap for GPU backends in real modules)."""

    dim: int

    def zeros(self) -> list[float]:
        return [0.0] * self.dim

    def dot(self, a: Vec, b: Vec) -> float:
        if len(a) != len(b):
            raise ValueError("vector length mismatch")
        return sum(x * y for x, y in zip(a, b, strict=True))


# --- math -------------------------------------------------------------------


class MathRole:
    """Scalar / reduction math (no I/O)."""

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


# --- db ---------------------------------------------------------------------


@dataclass(slots=True)
class DbRole:
    """DB / store façade — connect explicitly; never open at import time."""

    path: str
    _open: bool = False

    def connect(self) -> None:
        """Eager open — call from app startup, not at import (PEP 810)."""
        self._open = True

    def close(self) -> None:
        self._open = False

    @wrappers.logged
    def get(self, key: str) -> bytes | None:
        if not self._open:
            raise RuntimeError("db not connected")
        _ = key
        return None


# --- cowork (free-threading) ------------------------------------------------


class CoworkRole:
    """Parallel agent / step caps for GIL vs free-threaded Python 3.14+ (PEP 703)."""

    @staticmethod
    def gil_enabled() -> bool:
        """Return whether the GIL is enabled (``True`` on normal 3.14 builds)."""
        try:
            return sys._is_gil_enabled()
        except AttributeError:
            return True

    @staticmethod
    def parallel_cap() -> int:
        """Default concurrency cap: conservative on GIL, wider on free-threaded builds."""
        return 8 if CoworkRole.gil_enabled() else 32


# --- loop -------------------------------------------------------------------


class LoopRole:
    """Async / batch loop helpers."""

    @staticmethod
    async def gather_limited[T](
        coros: Sequence[Awaitable[T]],
        *,
        limit: int | None = None,
    ) -> list[T]:
        """Run awaitables with a concurrency cap (defaults to :meth:`CoworkRole.parallel_cap`)."""
        import asyncio  # deferred: only needed when this helper runs

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


# --- Python Static Template — role functions --------------------------------
# Free functions; same role order as classes
# -----------------------------------------------------------------------------


# --- type -------------------------------------------------------------------


def type_is_mapping(value: object) -> bool:
    return isinstance(value, dict)


# --- hint -------------------------------------------------------------------


def hint_tag(*tags: str) -> HintRole:
    return HintRole(name="tag", tags=tags)


# --- vect -------------------------------------------------------------------


@wrappers.timed
def vect_l2(a: Vec, b: Vec) -> float:
    if len(a) != len(b):
        raise ValueError("vector length mismatch")
    return sum((x - y) ** 2 for x, y in zip(a, b, strict=True)) ** 0.5


# --- math -------------------------------------------------------------------


def math_safe_div(num: float, den: float, default: float = 0.0) -> float:
    if den == 0.0:
        return default
    return num / den


# --- db ---------------------------------------------------------------------


def db_uri(path: str, *, read_only: bool = False) -> str:
    mode = "mode=ro" if read_only else "mode=rwc"
    return f"file:{path}?{mode}"


# --- loop -------------------------------------------------------------------


def loop_chunked[T](items: Sequence[T], size: int) -> list[Sequence[T]]:
    if size < 1:
        raise ValueError("size must be >= 1")
    return [items[i : i + size] for i in range(0, len(items), size)]


# --- cowork -----------------------------------------------------------------


def cowork_gil_enabled() -> bool:
    return CoworkRole.gil_enabled()


def cowork_parallel_cap() -> int:
    return CoworkRole.parallel_cap()


# --- Python Static Template — public surface --------------------------------
# Explicit ``__all__``; smoke via ``main()`` only when run as ``__main__``
# -----------------------------------------------------------------------------

__all__ = [
    "wrappers",
    "TypeRole",
    "HintRole",
    "VectRole",
    "MathRole",
    "DbRole",
    "LoopRole",
    "CoworkRole",
    "type_is_mapping",
    "hint_tag",
    "vect_l2",
    "math_safe_div",
    "db_uri",
    "loop_chunked",
    "cowork_gil_enabled",
    "cowork_parallel_cap",
]


def main() -> int:
    """Smoke the template locally: ``uv run python .cursor/templates/python_static_template.py``."""
    v = VectRole(dim=3)
    assert MathRole.clamp(v.dot([1, 0, 0], [1, 0, 0]), 0.0, 1.0) == 1.0
    assert loop_chunked([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

### Subtopic: Smoke check

```bash
uv run python .cursor/templates/python_static_template.py
```
