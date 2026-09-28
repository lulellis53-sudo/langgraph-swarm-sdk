# Codeworkspace

Multi-root layout for working on the LangGraph swarm SDK without moving the Python package.

| Folder in workspace | Repo path | Purpose |
|---------------------|-----------|---------|
| SDK (root) | `/` | `src/swarm_sdk`, `tests`, `pyproject.toml`, CI |
| Agents | `Agents/` | Role contracts (`AGENTS.md`), manifests (`agent.yaml`), coordination |
| Config | `config/` | Runtime wiring (`swarm.yaml`) — providers, models, vector, hybrid |
| Benchmark | `benchmark/` | `Tasks/{name}/` harnesses for token and retrieval metrics |

Open **swarm.code-workspace** in Cursor or VS Code. Paths in `Agents/coordination.yaml` stay relative to the repo root.
