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

## Shared agent vector store and graph graphic

```python
from pathlib import Path

from orchestration.agent_rag import ingest_agents, make_search
from orchestration.embedding import default_embedder
from orchestration.graph import build_graph
from orchestration.graphic import write_graph_files
from orchestration.vectorstore import SharedVectorStore

embedder = default_embedder()  # hash offline; fastembed if installed
store = SharedVectorStore(embedder.dim)
ingest_agents(Path("Agents"), store, embedder)  # each subfolder = one agent's RAG
store.save(Path("Core/Orchestration/.vectors"))

graph = build_graph(llm, make_search(store, embedder, agent="RAG", k=4))
write_graph_files(graph, Path("Core/Orchestration/docs"), name="orchestration")
```

All agents share one FAISS index; an agent's chunks occupy ids `slot << 40 | n`.
Pass `agent=None` to search every agent at once. `HashEmbedder` measures word
overlap, not meaning; install `fastembed` for dense vectors.
