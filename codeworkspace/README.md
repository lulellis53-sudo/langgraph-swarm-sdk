# Codeworkspace

Multi-root layout for working on the LangGraph swarm SDK without moving the Python package.

| Folder in workspace | Repo path | Purpose |
|---------------------|-----------|---------|
| SDK (root) | `/` | `src/swarm_sdk`, `tests`, `pyproject.toml`, CI |
| Agents | `Agents/` | Role contracts (`AGENTS.md`), manifests (`agent.yaml`), coordination |
| Config | `config/` | Runtime wiring (`swarm.yaml`) — providers, models, vector, hybrid |
| Benchmark | `benchmark/` | `Tasks/{name}/` harnesses for token and retrieval metrics |
| Docs | `docs/` | Layout and contributor notes (`LAYOUT.md`) |

Open **swarm.code-workspace** in Cursor or VS Code. Paths in `Agents/coordination.yaml` stay relative to the repo root.

**IDE config:** `.vscode/settings.json`, `.vscode/extensions.json`, and `.cursor/settings.json` / `.cursor/extensions.json` at the repo root. Use Python **3.14.5** from `.venv` after `uv sync --extra dev`.
