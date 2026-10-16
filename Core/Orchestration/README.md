# Core Orchestration

Offline LangGraph pipeline: **planner → researcher → writer**. The graph is built with `build_graph(llm, search)` in `orchestration/graph.py`.

## Run tests

From the repo root:

```bash
pixi run python -m pytest Core/Orchestration -q
```

## LangSmith tracing

Tracing is **environment-only**; no API keys are stored in this package.

| Variable | Effect |
| --- | --- |
| `LANGSMITH_TRACING` | Must be `true` (any case) to enable |
| `LANGSMITH_API_KEY` | Must be non-empty after strip |

Both must be set for `tracing_enabled()` to return `True`. CI and default local runs stay offline without these variables.

## Imports

- `from orchestration.graph import build_graph`
- Optional facade: `from Core.Lang import build_graph, tracing_enabled, GraphBuilder`
