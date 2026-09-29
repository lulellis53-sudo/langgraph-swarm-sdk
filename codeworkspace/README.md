# Codeworkspace

Multi-root layout for working on the LangGraph swarm SDK without moving the Python package.

| Folder in workspace | Repo path | Purpose |
|---------------------|-----------|---------|
| SDK (root) | `/` | `src/swarm_sdk`, `pyproject.toml`, CI |
| Agents | `Agents/` | Role contracts, manifests, `tests/`, shared `benchmark/` |
| Main | `Main/` | Embeddings/vectorstore re-exports, YAML, Essentials |
| Config | `Main/config/` | Runtime wiring (`swarm.yaml`) — providers, models, vector, hybrid |
| Benchmark | `Agents/benchmark/` | `Tasks/{name}/` harnesses for token and retrieval metrics |
| WebSearch | `WebSearch/` | Live-web research feature and persona |

Open **swarm.code-workspace** in Cursor or VS Code. Paths in `Agents/coordination.yaml` stay relative to the repo root.
