# Agent guidelines — LangGraph Swarm SDK

Instructions for humans and AI assistants working in this repository. Read this first; drill into specialist docs only when your task requires them.

## What this project is

**LangGraph Swarm SDK** — a Python library and runtime for parallel multi-LLM swarms: LangGraph handoffs, semantic cache, hybrid retrieval, reranking, token budgets, and optional HTTP/gRPC APIs. The design goal is **fewer tokens** and **more relevant context**, not maximal model verbosity.

Human-oriented overview: [`README.md`](README.md).

## Repository map

| Path | Purpose |
|------|---------|
| [`src/swarm_sdk/`](src/swarm_sdk/) | Library: swarm runtime, cache, memory, routing, API/gRPC |
| [`src/swarm_sdk/orchestrator/`](src/swarm_sdk/orchestrator/) | Parallel plan engine: `spawn` (goal → JSON plan) + `run_plan` (LangGraph dependency waves) |
| [`src/swarm_sdk/pb/`](src/swarm_sdk/pb/) | gRPC: `swarm.proto` + generated `swarm_pb2*` stubs |
| [`config/swarm.yaml`](config/swarm.yaml) | Provider registry, routes, defaults (`SWARM_*` env overrides) |
| [`Agents/`](Agents/) | Specialist **swarm personas** (`AGENTS.md` + `agent.yaml` per role) |
| [`Agents/coordination.yaml`](Agents/coordination.yaml) | Task graph for multi-agent workflows |
| [`Agents/README.md`](Agents/README.md) | Index of swarm agents and how to run them |
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

## Environment and commands

- **Python:** `>=3.14.5`, managed with **[uv](https://docs.astral.sh/uv/)**.
- **Install:** `uv sync --extra dev` (add `--extra faiss`, `--extra faiss-gpu`, `--extra embed`, `--extra molten`, `--extra observability`, `--extra qdrant`, `--extra jupyter` as needed).
- **Run services:** `uv run swarm-api`, `uv run swarm-grpc`.
- **Quality gate** (run before claiming work is done):

```bash
uv run --extra dev pytest tests benchmark -q
uv run --extra dev ruff check src tests benchmark
uv run --extra dev ty check src tests benchmark
uv run python -m swarm_sdk.agents.validate
```

Use `uv run …` so commands use the project virtualenv.

### Colab and Codex (editor)

- **Colab** (`google.colab`): open a `.ipynb` → **Select Kernel** → **Colab** → sign in with Google. Requires `uv sync --extra jupyter` for local kernels; Colab runs remotely.
- **Codex** (`openai.chatgpt`): open the Codex sidebar and sign in with ChatGPT. Repo defaults: [`.codex/config.toml`](.codex/config.toml). For LangChain Codex routes, set `CODEX_OAUTH_TOKEN` in `.env` (see [`config/model_registry.yaml`](config/model_registry.yaml)).
- **Install extensions:** Cursor/VS Code will prompt from [`.vscode/extensions.json`](.vscode/extensions.json), or `xargs -n1 code --install-extension < .cursor/extensions.txt`.

## Two kinds of “agents”

1. **Coding assistant (you in Cursor)** — edits this repo, runs tests, opens PRs. Follow the sections below.
2. **Swarm specialists (`Agents/*`)** — fictional roles (Coder, Tester, Security, …) with JSON output contracts for orchestrated tasks. When emulating a role, read that folder’s [`AGENTS.md`](Agents/Coder/AGENTS.md) and obey its contract. When doing general repo work, use this file and the Coder-style norms (minimal diff, tests, no secrets).

For swarm coordination: start from [`Agents/README.md`](Agents/README.md) and [`Agents/coordination.yaml`](Agents/coordination.yaml).

## How to change code

1. **Read first** — callers, tests, and config that touch the same behavior.
2. **Smallest correct diff** — no drive-by refactors, new abstractions, or dependencies unless the task requires them.
3. **Match conventions** — Ruff (`line-length = 100`, py314), existing naming and patterns in `src/swarm_sdk/`.
4. **Prove it** — failing test → fix → full gate above. Do not weaken lint/type checks without a named rule and reason.
5. **Config** — prefer [`config/swarm.yaml`](config/swarm.yaml) and agent manifests under `Agents/*/agent.yaml`; document new env vars in README or agent docs.
6. **Protobuf** — edit [`src/swarm_sdk/pb/swarm.proto`](src/swarm_sdk/pb/swarm.proto), then regenerate with `uv run python -m swarm_sdk.pb`. Do not hand-edit `swarm_pb2*` stubs.
7. **New Python modules** — copy from [@.cursor/templates/python_static_template.py](.cursor/templates/python_static_template.py); see **Static Templates** below.

## Benchmarks and SQL Pro

- Benchmark tasks live under [`benchmark/Tasks/`](benchmark/Tasks/); results go to `benchmark/results/` (gitignored).
- SQL Pro suite: [`benchmark/sql_pro/suite.yaml`](benchmark/sql_pro/suite.yaml), CLI `uv run python -m benchmark.sql_pro.run`, Cursor command [`.cursor/commands/sql-pro.md`](.cursor/commands/sql-pro.md).

## Security and secrets

- Never commit `.env`, API keys, tokens, or credentials.
- Never paste secret values into issues, logs, or agent output (report path/pattern only — see [`Agents/Security/AGENTS.md`](Agents/Security/AGENTS.md)).
- Do not add network calls that exfiltrate repo data unless the user explicitly asks.

## Git and docs

- **Commits:** only when the user asks; do not force-push `main`.
- **Docs:** update [`README.md`](README.md) when behavior or install steps change; keep agent-specific rules in `Agents/*/AGENTS.md`.
- **Dependencies:** add via `pyproject.toml` / `uv lock`; respect `[tool.uv]` constraints (e.g. `cryptography` wheel-only for Jupyter extra).

## When stuck

- Report `blocked` with the exact command output after one reasonable retry.
- Prefer fixing the environment (uv sync, missing extra) over skipping tests.
- For provider/model behavior, read [`config/swarm.yaml`](config/swarm.yaml) and [`src/swarm_sdk/model_select.py`](src/swarm_sdk/model_select.py).

## Static Templates

Canonical scaffold (Cursor `@` attach): [@.cursor/templates/python_static_template.py](.cursor/templates/python_static_template.py)

Rule: [`.cursor/rules/python-static-template.mdc`](.cursor/rules/python-static-template.mdc). Ops: [`.cursor/AGENTS.md`](.cursor/AGENTS.md). Every `Agents/*/AGENTS.md` links here too.

> There is no **PEP 850**. Use **[PEP 810 – Explicit lazy imports](https://peps.python.org/pep-0810/)** for deferred-import–safe modules (Python 3.15+ syntax; write 3.14 modules without import-time side effects so they stay eligible).

### When to use

- Creating a **new** module under `src/swarm_sdk/` (not drive-by edits).
- Copy the file, rename it, **delete unused role sections**, keep remaining roles contiguous.
- Do **not** import the template from runtime package code.

### Required shape (merged from the template)

1. Module docstring + `from __future__ import annotations`
2. Stdlib / third-party / local imports (no import-time I/O; heavy deps deferred)
3. **`wrappers`** — decorator namespace; use `@wrappers.timed`, `@wrappers.logged`, `@wrappers.retry(n)` (always `@functools.wraps`)
4. **Role classes** (order): `Type` → `Hint` → `Vect` → `Math` → `Db` → `Loop` (add only what you need)
5. **Role functions** with the same prefixes: `type_`, `hint_`, `vect_`, `math_`, `db_`, `loop_`
6. Explicit `__all__` (+ optional `main` smoke under `__main__` only)

### Roles at a glance

| Role | Class | Functions | Concern |
|------|--------|-----------|---------|
| type | `TypeRole` | `type_*` | Protocols, narrowers |
| hint | `HintRole` | `hint_*` | Annotations / metadata |
| vect | `VectRole` | `vect_*` | Vectors / embeddings math |
| math | `MathRole` | `math_*` | Scalar / reductions (no I/O) |
| db | `DbRole` | `db_*` | Store / connection façade |
| loop | `LoopRole` | `loop_*` | Async / batch iteration |

### PEP 810 checklist

- Module body = defs/classes/constants only (no connect/register/spawn at import).
- Explicit `connect()` / `register()` called by the app — not at import.
- Optional heavy imports inside the function (3.14) or `lazy import` (3.15+).
- Type-only names under `if TYPE_CHECKING:`.

Smoke check after copying:

```bash
uv run python .cursor/templates/python_static_template.py
```

## Quick links

- Agent index: [`Agents/README.md`](Agents/README.md)
- Workspace layout: [`codeworkspace/swarm.code-workspace`](codeworkspace/swarm.code-workspace)
- Benchmarks: [`benchmark/README.md`](benchmark/README.md)
- Static template: [@.cursor/templates/python_static_template.py](.cursor/templates/python_static_template.py)
- PEP 810: <https://peps.python.org/pep-0810/>
