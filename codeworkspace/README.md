# Codeworkspace

Multi-root layout for working on the LangGraph swarm SDK without moving the Python package.

| Folder in workspace | Repo path | Purpose |
|---------------------|-----------|---------|
| SDK (root) | `/` | `src/swarm_sdk`, `pyproject.toml`, CI |
| Agents | `Agents/` | Role contracts, manifests, `tests/`, shared `benchmark/` |
| Main | `Main/` | Embeddings/vectorstore re-exports, YAML, Essentials |
| Config | `Main/config/` | Runtime wiring (`swarm.yaml`) — providers, models, vector, hybrid |
| Benchmark | `Agents/benchmark/` | `Tasks/{name}/` harnesses for token and retrieval metrics |
| WebSearch | `WebSearch/` | Symlink to `../Swarm-WebSearch` worktree (`worktree/websearch`) |

Open **swarm.code-workspace** in Cursor or VS Code. Paths in `Agents/coordination.yaml` stay relative to the repo root.

**IDE config:** `.vscode/settings.json`, `.vscode/extensions.json`, and `.cursor/settings.json` / `.cursor/extensions.json` at the repo root. Use Python **3.14.5** from `.venv` after `uv sync --extra dev`.
