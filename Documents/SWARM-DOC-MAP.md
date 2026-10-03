# Swarm documentation map (repo index)

Personal canonical bridge manual: **`~/Documentos/SwarmSDK-Bridge.md`**. Edit that file first for cross-repo layout, quality gate, and lane table; keep this stub in sync when those sections change.

| Repo path | Personal / related |
| :--- | :--- |
| [README.md](../README.md) | Install, serving, LangGraph Server |
| [AGENTS.md](../AGENTS.md) | Contributor workflow, quality gate |
| [Toolchain.md](../Toolchain.md) | Host silicon + verification commands |
| [CLI.md](../CLI.md) | `low-swarm`, `swarm-vault`, entrypoints |
| [Documents/LangGraphSwarm.md](LangGraphSwarm.md) | Architecture manual (large) |
| [Documents/RAGTECHNIQUES.MD](RAGTECHNIQUES.MD) | RAG research |
| [Agents/RAG/AGENTS.md](../Agents/RAG/AGENTS.md) | RAG specialist contract |
| [.cursor/skills/multi-lane-worktrees/SKILL.md](../.cursor/skills/multi-lane-worktrees/SKILL.md) | Three-lane worktrees |

Quality gate (from repo root):

```bash
uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 pytest Agents/benchmark -q
uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 ruff check src Agents/benchmark Main
uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 ty check src Agents/benchmark Main
uv run python -m swarm_sdk.agents.validate
```
