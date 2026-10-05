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
| [Documents/AGENTMEMORY.md](AGENTMEMORY.md) | Multi-tier agent memory, Mem0 APIs, subagent handoff protocols & self-learning feedback |
| [Documents/GRAPH.md](GRAPH.md) | 2026 Graph architectures for embeddings, memory graph, and multi-agent coordination |
| [Documents/RAG.md](RAG.md) | 2026 GraphRAG, CRAG, Self-RAG, FastEmbed & Redis 7.4/8.0 vector indexing manual |
| [Documents/DATABASE.md](DATABASE.md) | Enterprise DB architectures, PostgreSQL 17 + pgvector 0.8.0+, sqlite-vec & PgCat |
| [Documents/VectorDB.md](VectorDB.md) | Vector DB engines, LanceDB DiskANN, Redis 7.4/8.0 VSS, Qdrant & FastEmbed |
| [Documents/DeepResearch.md](DeepResearch.md) | Multi-engine DeepResearch framework (#Context7, #Exa, #Brave, #ParallelSearch, #Jira, #BrightData) |
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
