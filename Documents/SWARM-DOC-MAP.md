# Swarm documentation map (repo index)

Personal canonical bridge manual: **`~/Documentos/SwarmSDK-Bridge.md`**. Edit that file first for cross-repo layout, quality gate, and lane table; keep this stub in sync when those sections change.

| Repo path | Personal / related |
| :--- | :--- |
| [README.md](../README.md) | Install, serving, LangGraph Server |
| [AGENTS.md](../AGENTS.md) | Contributor workflow, quality gate |
| [Toolchain.md](../Toolchain.md) | Host silicon + verification commands |
| [CLI.md](../CLI.md) | `low-swarm`, `swarm-vault`, entrypoints |
| [Documents/LangGraphSwarm.md](LangGraphSwarm.md) | Architecture manual (large) |
| [Documents/LowResourceOptimization.md](LowResourceOptimization.md) | Low-resource systems, zero-copy PyArrow/Polars, NumPy 2.x, LangSmith |
| [Documents/RAGTECHNIQUES.MD](RAGTECHNIQUES.MD) | RAG research & 2026 late chunking / V-RAG 1.0 benchmarks |
| [Documents/Python3.15.md](Python3.15.md) | 3.15 dossier; §11.3 ↔ `Agents/benchmark/Tasks/python315_claims/` |
| [Agents/TEMPLATE.md](../Agents/TEMPLATE.md) | Canonical Specialist Agent Persona & JSON Contract Template |
| [Agents/AgentMethods.md](../Agents/AgentMethods.md) | Canonical 12 Agent Methods (DARS, ReAct, Reflection, SWE, etc.) |
| [Agents/RAG/AGENTS.md](../Agents/RAG/AGENTS.md) | RAG specialist contract |
| [.cursor/skills/multi-lane-worktrees/SKILL.md](../.cursor/skills/multi-lane-worktrees/SKILL.md) | Three-lane worktrees |
| [Research Dossier](file:///Users/usuario/Documentos/LANGGRAPH_SWARM_ACCELERATION_RESEARCH.md) | LangSmith, PyArrow, Polars & NumPy 2.x acceleration dossier |

Quality gate (from repo root):

```bash
uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 pytest Agents/benchmark -q
uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 ruff check src Agents/benchmark Main
uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 ty check src Agents/benchmark Main
uv run python -m swarm_sdk.agents.validate
```
