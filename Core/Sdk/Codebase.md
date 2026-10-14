# Swarm Core SDK Codebase Specification

## 1. Architectural Role & Invariants

The `Core/` tree is the authoritative platform root for the `langgraph-swarm-sdk` monorepo. It houses the engine runtimes, framework integrations, and graph state machinery used across product worktrees (`Newsletter/`, `TechNews/`, `BotDeal/`).

### Invariant Rules
1. **Single Source of Truth**: `Core/src/swarm_sdk/` is the canonical package directory. `Swarm/src/swarm_sdk` is a symlink pointing to `../Core/src/swarm_sdk`. Do not duplicate files between them.
2. **Framework Decoupling**: LangGraph, LangChain, and LangSmith integration logic resides in dedicated submodules:
   - `swarm_sdk.langgraph`: Graph state definitions, checkpointers, and handoff assemblies.
   - `swarm_sdk.langchain`: Chat model initialization, prompt templates, and agent middleware.
   - `swarm_sdk.langsmith`: Tracing clients, run lifecycle callbacks, and dataset evaluators.
3. **Cross-Lane Sharing**: Shared configurations, system prompt fragments, and schemas reside in `Swarm/Shared/` (aliased as `Swarm/Share`).
4. **Environment Discipline**: Runtimes are governed by `pixi.toml` (targeting Python 3.15) and packaged via `pyproject.toml` (Hatchling).

---

## 2. Directory Tree Map

```text
Core/
├── Sdk/
│   ├── Codebase.md                 # System specification (this document)
│   ├── Readme.md                   # Developer user guide and quickstart
│   └── Changelog.md                # Evolution ledger and version milestones
│
└── src/
    └── swarm_sdk/                  # Root Python namespace
        ├── __init__.py             # Public top-level exports
        ├── cli.py                  # CLI entrypoints (low-swarm, swarm-chat)
        │
        ├── core/                   # Low-level primitives
        │   ├── swarm.py            # SwarmSDK core orchestrator
        │   ├── graph_builder.py    # Manifest-driven graph compiler
        │   ├── checkpoint.py       # Checkpoint saver adapters
        │   ├── jev_router.py       # Fast-path deterministic router
        │   └── rules.py            # Guardrail validations
        │
        ├── langgraph/              # LangGraph framework integration
        │   ├── __init__.py         # GraphBuilder, build_swarm_graph
        │   └── state.py            # TypedDict state channels & message reducers
        │
        ├── langchain/              # LangChain ecosystem bindings
        │   ├── __init__.py         # Model loaders & prompt adapters
        │   └── middleware.py       # Summarization & context pruning
        │
        ├── langsmith/              # LangSmith observability
        │   ├── __init__.py         # Lazy client loader & callback handler
        │   ├── client.py           # Configuration validation
        │   └── callbacks.py        # Real-time event tracking
        │
        ├── orchestrator/           # High-level dispatch
        │   ├── graph.py            # StateGraph definitions
        │   ├── spawn.py            # Concurrent agent runner
        │   └── plan.py             # Plan generation & evaluation
        │
        └── observability/          # OpenTelemetry, metrics, usage
            ├── tracing.py          # OTel span hooks
            ├── metrics.py          # Latency & throughput counters
            └── usage.py            # Token budget monitoring
```

---

## 3. Data Flow & Handoff Mechanics

```text
User Request
    │
    ▼
[JEV Fast-Path Router] ──(Deterministic Node Pick)──► [Entry Agent: Researcher]
    │                                                               │
    ▼                                                               ▼
[LangGraph StateGraph] ◄────────(create_handoff_tool)───────── [Worker Agents]
    │                                                               │
    ├────────► [LangSmith Tracer Callback] ──► (Traces, Tokens, Latency)
    │
    ▼
[Checkpointer (Sqlite / Memory)] ──► State Persistence & Recovery
```

---

## 4. Package Integration & Wheel Generation

Under `pyproject.toml`:
```toml
[tool.hatch.build]
dev-mode-dirs = [".", "src", "Core/src"]

[tool.hatch.build.targets.wheel]
packages = ["src/swarm_sdk", "WebSearch"]
```
Because `src/swarm_sdk` links directly to `Core/src/swarm_sdk`, all modules within `Core/src/swarm_sdk/` are packaged directly into the distribution wheel with zero file copying.
