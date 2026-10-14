# Swarm Core SDK

High-performance, multi-agent orchestration SDK built on LangGraph Swarm, LangChain, and LangSmith.

```text
# (Canonical Architecture)
                 +----------------------+
                 |        SDK           |
                 |  . LangGraph         |
                 |  . Project Configs   |
                 |  . Share             |
                 |  . src               |
                 |  # Python 3.15       |
                 |  # pyproject.toml    |
                 +----------------------+
                            |
      +-----------+---------+----------+-----------+
      |           |         |          |
      v           v         v          v
 +----------+ +----------+ +----------+ +----------+
 | Modules  | |  Agents  | |  Tools   | |  Vector  |
 +----------+ +----------+ +----------+ +----------+
      |            |            |
      +-- Newsletter +-- RAG      +-- Swarm
      +-- BotDeal    +-- Memory   +-- Prediction
      +-- TechNews                +-- WebSearch
                                  +-- WebScraper
```

---

## Overview

The **Swarm Core SDK** powers autonomous multi-agent systems with:
- **LangGraph Swarm Orchestration**: State-driven execution graphs, handoff tools, and checkpoint persistence (`SqliteSaver`, `InMemorySaver`).
- **LangChain Bridges**: Unified chat model initializers (`load_chat_model`), context editing, and agent middleware.
- **LangSmith Observability**: End-to-end tracing, latency tracking, token usage auditing, and dataset evaluation.
- **Cross-Lane Shared Resources**: Centralized shared configurations and schemas under `Shared/` (accessible via `Share/` symlink).

---

## Directory Layout

```text
Core/
├── Sdk/                            # Top-level SDK façade & documentation
│   ├── Codebase.md                 # Technical codebase specification
│   ├── Readme.md                   # This document
│   └── Changelog.md                # Release and change records
│
└── src/
    └── swarm_sdk/                  # Canonical Python package (symlinked at Swarm/src/swarm_sdk)
        ├── core/                   # Swarm orchestration, graph assembly, router
        ├── orchestrator/           # Worker coordination & task execution
        ├── observability/          # OpenTelemetry, metrics, usage
        ├── langgraph/              # LangGraph orchestration state & graph builders
        ├── langchain/              # LangChain chat models, prompts, middleware
        └── langsmith/              # LangSmith tracing client & callbacks
```

---

## Quickstart & Imports

### 1. LangGraph Swarm Workflows
```python
from swarm_sdk.langgraph import GraphBuilder, init_checkpointer
from swarm_sdk.core.swarm import SwarmSDK

sdk = SwarmSDK()
builder = GraphBuilder(sdk)
graph = builder.compile()
```

### 2. LangChain Chat Models
```python
from swarm_sdk.langchain import load_chat_model

# Loads chat model with automatic fallback routing
model = load_chat_model("deepseek/deepseek-chat")
response = model.invoke("Hello, Swarm!")
```

### 3. LangSmith Tracing
```python
from swarm_sdk.langsmith import get_langsmith_client, is_langsmith_enabled

if is_langsmith_enabled():
    client = get_langsmith_client()
    print("LangSmith tracing active for project:", client)
```

---

## Environment Configuration

Configure credentials dynamically via environment variables or Keychain/1Password:
```bash
# LangSmith Tracing
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY="lsv2_pt_..."
LANGCHAIN_PROJECT="swarm-sdk-production"

# LLM Providers
OPENAI_API_KEY="..."
ANTHROPIC_API_KEY="..."
DEEPSEEK_API_KEY="..."
```

---

## Development & Testing

Run automated tests through `pixi` or `uv`:
```bash
# Verify package layout
uv run pytest tests/test_package_layout.py -v

# Run full test suite
uv run pytest tests/
```
