# Swarm documentation map (repo index)

Personal canonical bridge manual: **`~/Documentos/SwarmSDK-Bridge.md`**. Edit that file first for cross-repo layout, quality gate, and lane table; keep this stub in sync when those sections change.

| Repo path | Personal / related |
| :--- | :--- |
| [README.md](../README.md) | Install, serving, LangGraph Server |
| [AGENTS.md](../AGENTS.md) | Contributor workflow, quality gate |
| [Toolchain.md](../Toolchain.md) | Host silicon + verification commands |
| [CLI.md](../CLI.md) | `low-swarm`, `swarm-vault`, entrypoints |
| [Documents/LangSwarm.md](LangSwarm.md) | Canonical LangGraph Swarm manual (merged `LangGraphSwarm.md`, `LANGGRAPH_SWARM_ACCELERATION_RESEARCH.md`) |
| [Documents/LangGraphSwarm.md](LangGraphSwarm.md) | Stub → `LangSwarm.md` |
| [Documents/LANGGRAPH_SWARM_ACCELERATION_RESEARCH.md](LANGGRAPH_SWARM_ACCELERATION_RESEARCH.md) | Stub → `LangSwarm.md` Part 0 |
| [Documents/LowResourceOptimization.md](LowResourceOptimization.md) | Low-resource systems, zero-copy PyArrow/Polars, NumPy 2.x, LangSmith |
| [Documents/RAGTECHNIQUES.MD](RAGTECHNIQUES.MD) | Canonical RAG dossier (merged `RAG.md`); Swarm SDK map + benchmarks |
| [Documents/RAG.md](RAG.md) | Stub → `RAGTECHNIQUES.MD` |
| [Documents/Python3.15.md](Python3.15.md) | 3.15 dossier (includes merged free-threading + performance guides); §11.4 ↔ `python315_claims/` |
| [Documents/PythonFreeThreadedRuntime.md](PythonFreeThreadedRuntime.md) | Stub → `Python3.15.md` §2.1.1, §11.3 |
| [Documents/PythonPerformanceGuide.md](PythonPerformanceGuide.md) | Stub → `Python3.15.md` §2.1.2–§2.1.3, §11.2 |
| [Documents/REDIS.md](REDIS.md) | Canonical Redis + caching (§1–§7 ops, §8 SDK exact cache, §9 multi-tier); `redis_cache` benchmark |
| [Documents/redis-cache.md](redis-cache.md) | Stub → `REDIS.md` §8 |
| [Documents/Benchmark.md](Benchmark.md) | Canonical benchmark methodologies, latency thresholds & statistical metrics |
| [Documents/Numba.md](Numba.md) | Numba JIT hardware acceleration, SIMD AVX2/AVX-512, NUMA & cuTile GPU manual |
| [Documents/CACHING.md](CACHING.md) | Stub → `REDIS.md` §9 |
| [Documents/LLMLITE.md](LLMLITE.md) | Lightweight LLM engines (vLLM, Ollama, llama.cpp, FastEmbed) & GGUF quantization |
| [Documents/SERIALIZATION.md](SERIALIZATION.md) | High-performance serialization, Apache Arrow IPC, zero-copy PyArrow & orjson benchmarks |
| [Documents/AGENTMEMORY.md](AGENTMEMORY.md) | Canonical agent memory + vector DB dossier (merged `VectorDB.md`); Mem0, handoffs, LanceDB/Redis/Qdrant |
| [Documents/VectorDB.md](VectorDB.md) | Stub → `AGENTMEMORY.md` |
| [Documents/GRAPH.md](GRAPH.md) | 2026 Graph architectures for embeddings, memory graph, and multi-agent coordination |
| [Documents/Lifeguard.md](Lifeguard.md) | Lifeguard layers: Meta lazy-import CLI, `MetaLifeguardAuditor`, LifeguardSystem ops, RSS/`healthz` |
| [Documents/Database.md](Database.md) | Canonical DB dossier (merged `DATABASE.md`, `DB.md`); pgvector, sqlite-vec, DuckDB, LangGraph persistence (`DATABASE.md` is same path on case-insensitive volumes) |
| [Documents/DB.md](DB.md) | Stub → `Database.md` |
| [Documents/DeepResearch.md](DeepResearch.md) | Multi-engine DeepResearch framework (#Context7, #Exa, #Brave, #ParallelSearch, #Jira, #BrightData) |
| [Agents/TEMPLATE.md](../Agents/TEMPLATE.md) | Canonical Specialist Agent Persona & JSON Contract Template |
| [Agents/AgentMethods.md](../Agents/AgentMethods.md) | Canonical 12 Agent Methods (DARS, ReAct, Reflection, SWE, etc.) |
| [Agents/RAG/AGENTS.md](../Agents/RAG/AGENTS.md) | RAG specialist contract |
| [.cursor/skills/multi-lane-worktrees/SKILL.md](../.cursor/skills/multi-lane-worktrees/SKILL.md) | Three-lane worktrees |
| [Research Dossier](file:///Users/usuario/Documentos/LANGGRAPH_SWARM_ACCELERATION_RESEARCH.md) | Extended host copy (LangSmith, PyArrow, Polars, NumPy 2.x); repo summary in `LangSwarm.md` Part 0 |

Quality gate (from repo root):

```bash
uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 pytest Agents/benchmark -q
uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 ruff check src Agents/benchmark Main
uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 ty check src Agents/benchmark Main
uv run python -m swarm_sdk.agents.validate
```
