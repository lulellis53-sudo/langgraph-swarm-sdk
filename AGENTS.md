# Agent guidelines — LangGraph Swarm SDK

## Summary

Instructions for humans and AI assistants working in this repository. Read this first; drill into specialist docs only when your task requires them.

| Topic                                                     | What you will find                                                               |
| --------------------------------------------------------- | -------------------------------------------------------------------------------- |
| [Project overview](#topic-project-overview)               | What LangGraph Swarm SDK is; coding assistant vs swarm specialists               |
| [Repository layout](#topic-repository-layout)             | Path map; protobuf note; quick links                                             |
| [Development environment](#topic-development-environment) | Python/uv, services, quality gate, Colab, extensions                       |
| [Workflow](#topic-workflow)                               | How to change code; when stuck                                                   |
| [Benchmarks](#topic-benchmarks)                           | Task layout; SQL Pro suite                                                       |
| [Security and compliance](#topic-security-and-compliance) | Secrets; network exfiltration                                                    |
| [Git and documentation](#topic-git-and-documentation)     | Commits, README, dependencies                                                    |
| [Python Static Template](#topic-python-static-template)   | Lite + full `.py` scaffolds; agent contract; link only (no inline paste) |

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
| `[src/swarm_sdk/server/](src/swarm_sdk/server/)`             | LangGraph Server graph factories referenced by `[langgraph.json](langgraph.json)` (`swarm`, `plan`)       |
| `[src/swarm_sdk/serving/client.py](src/swarm_sdk/serving/client.py)` | `langgraph_sdk` client; `SWARM_SERVER_URL` delegates runs to a LangGraph Server                    |
| `[langgraph.json](langgraph.json)`                           | LangGraph Server manifest mapping the `swarm` and `plan` graph ids to factory functions                   |
| `[src/swarm_sdk/pb/](src/swarm_sdk/pb/)`                     | gRPC: `swarm.proto` + generated `swarm_pb2*` stubs                                                       |
| `[Main/config/swarm.yaml](Main/config/swarm.yaml)`           | Provider registry, routes, defaults (`SWARM_*` env overrides)                                            |
| `[Main/](Main/)`                                             | Embeddings/vectorstore re-exports, YAML, Essentials                                                      |
| `[WebSearch/](WebSearch/)`                                   | Git worktree (`feature/websearch`): search pipeline — see `[WebSearch/PIPELINE.md](WebSearch/PIPELINE.md)` |
| `[Prediction/](../Swarm-Prediction/Prediction/)`               | Git worktree (`feat/prediction-engine`): mlforecast engine — sibling `../Swarm-Prediction` |
| `[Newsletter/](../Newsletter/Newsletter/)`                   | Git worktree (`feat/newsletter`): offline digest MVP — sibling `../Newsletter` |
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
| `[Documents/](Documents/)`                                     | Architecture manuals; doc map: `[Documents/SWARM-DOC-MAP.md](Documents/SWARM-DOC-MAP.md)` ↔ `~/Desktop/Documentos/SwarmSDK-Bridge.md` |

Edit `[src/swarm_sdk/pb/swarm.proto](src/swarm_sdk/pb/swarm.proto)` then `uv run python -m swarm_sdk.pb` to regenerate stubs. Never commit `.env`.

### Subtopic: Quick links

- Agent index: `[Agents/SKILLS.md](Agents/SKILLS.md)`
- Workspace layout: `[codeworkspace/swarm.code-workspace](codeworkspace/swarm.code-workspace)`
- Benchmarks: `[Agents/benchmark/README.md](Agents/benchmark/README.md)`
- Toolchains and CPython support: `[Toolchain.md](Toolchain.md)`
- Personal ↔ repo doc bridge: `[Documents/SWARM-DOC-MAP.md](Documents/SWARM-DOC-MAP.md)`
- Static template: [@.cursor/templates/python_static_template.py](.cursor/templates/python_static_template.py)

---

## Topic: Development environment

### Subtopic: Python and uv

- **Python:** `>=3.14.5`, managed with **[uv](https://docs.astral.sh/uv/)**.
- **Install:** `uv sync --extra dev` (add `--extra faiss`, `--extra faiss-gpu`, `--extra embed`, `--extra molten`, `--extra observability`, `--extra qdrant`, `--extra mem0`, `--extra jupyter` as needed).

Use `uv run …` so commands use the project virtualenv.

### Subtopic: Services

- **Run services:** `uv run swarm-api`, `uv run swarm-grpc`.
- **LangGraph Server:** `[langgraph.json](langgraph.json)` serves the `swarm` (handoff graph) and `plan` (spawn → wave engine) graphs; factories in `[src/swarm_sdk/server/graphs.py](src/swarm_sdk/server/graphs.py)`. Deploy with `langgraph up` (the pinned `langgraph-cli` for Python 3.14 has no in-memory `dev` server), then call it with `SWARM_SERVER_URL=http://127.0.0.1:2024` — `SwarmSDK.run` delegates to the server via `langgraph_sdk` (`swarm_sdk.serving.client`). `swarm-api`/`swarm-grpc` remain the in-process serving paths.

### Subtopic: Quality gate

Run before claiming work is done:

```bash
uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 pytest Agents/benchmark -q
uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 ruff check src Agents/benchmark Main
uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 ty check src Agents/benchmark Main
uv run python -m swarm_sdk.agents.validate
```

### Subtopic: Colab

- **Colab** (`google.colab`): open a `.ipynb` → **Select Kernel** → **Colab** → sign in with Google. Requires `uv sync --extra jupyter` for local kernels; Colab runs remotely.
- **LangChain Codex routes:** set `CODEX_OAUTH_TOKEN` in `.env` (see `[Main/config/model_registry.yaml](Main/config/model_registry.yaml)`).

### Subtopic: Editor extensions

- Cursor/VS Code will prompt from `[.vscode/extensions.json](.vscode/extensions.json)`, or `xargs -n1 code --install-extension < .cursor/extensions.txt`.

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
- YAML (`agent.yaml`, `model_registry.yaml`, `coordination.yaml`, `swarm.yaml`) holds env-var **names** only (`api_key_env: ZHIPU_API_KEY`), never values. `test_yaml_never_holds_secret_values` enforces this; keep it green.
- Never paste secret values into issues, logs, or agent output (report path/pattern only — see `[Agents/Security/AGENTS.md](Agents/Security/AGENTS.md)`).

### Subtopic: Network

- Do not add network calls that exfiltrate repo data unless the user explicitly asks.

---

## Topic: Git and documentation

### Subtopic: Commits

- **Commits:** only when the user asks; do not force-push `main`.
- **Branches / worktrees:** use only the three fixed agent lanes plus `integration/all-branches` at repo root. See [`.cursor/skills/multi-lane-worktrees/SKILL.md`](.cursor/skills/multi-lane-worktrees/SKILL.md).

### Subtopic: Documentation

- **Docs:** update `[README.md](README.md)` when behavior or install steps change; keep agent-specific rules in `Agents/*/AGENTS.md`.

### Subtopic: Dependencies

- **Dependencies:** add via `pyproject.toml` / `uv lock`; respect `[tool.uv]` constraints (e.g. `cryptography` wheel-only for Jupyter extra).

---

## Topic: Python Static Template

Runnable (full): [@.cursor/templates/python_static_template.py](.cursor/templates/python_static_template.py).  
Default for small modules (lite): [@.cursor/templates/python_static_template_lite.py](.cursor/templates/python_static_template_lite.py).

Rule: [`.cursor/rules/python-static-template.mdc`](.cursor/rules/python-static-template.mdc). Ops: [`.cursor/AGENTS.md`](.cursor/AGENTS.md). **Do not** paste the full template into this file — single source of truth is the `.py` files (CI enforces).

### Subtopic: Mandatory first import

Module docstring, then immediately:

```python
from __future__ import annotations
```

### Subtopic: Agent contract

- Read callers, tests, and config before editing.
- One failed attempt → analyse → one deliberate fix (no blind retries).
- Profile before optimizing; use `SWARM_PROFILE=1` only for `@wrappers.timed` on non-hot paths.
- Parallel swarm steps: disjoint `files` per sibling; cap via `cowork_parallel_cap()` / `swarm_sdk.execution.concurrency.parallel_cap`.
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
| cowork | `CoworkRole` | `cowork_*` | PEP 703 caps; runtime: `swarm_sdk.execution.concurrency` |

### Subtopic: Wrappers

- `@wrappers.retry_transient(times=2, on=(TimeoutError, OSError, ConnectionError))` — not for logic bugs.
- `@wrappers.timed` — active only when `SWARM_PROFILE` is set.

### Subtopic: Smoke check

```bash
uv run python .cursor/templates/python_static_template.py
uv run python .cursor/templates/python_static_template_lite.py
```
