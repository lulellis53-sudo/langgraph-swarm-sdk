# Agent Memory & Vector Storage for Multi-Agent Swarms

> **CANONICAL DOSSIER** (merged `VectorDB.md`): multi-tier agent memory, Mem0-style orchestration, and vector database engine selection.
> Runtime behavior: [`src/swarm_sdk/retrieval/`](../src/swarm_sdk/retrieval/), [REDIS.md](REDIS.md) §8 (exact cache), [RAGTECHNIQUES.MD](RAGTECHNIQUES.MD) §11.1 (survey of Mem0 / Zep / Graphiti).

---

## How to use this document

Use the index to jump to **memory orchestration** (Parts I–II) or **vector engine trade-offs** (Parts III–V). Benchmark tables are illustrative unless tied to a repo benchmark; verify on your hardware and corpus.

## Swarm SDK implementation map

| Topic | Swarm module / config | Notes |
| :--- | :--- | :--- |
| Embeddings (FastEmbed default) | `retrieval/embeddings.py`, `Settings.embed_backend` | ONNX CPU path; deterministic hash embedder for tests |
| Vector index (local) | FAISS ingest in `cli.py` `ingest` | `--output` on-disk index |
| Hybrid retrieval | `retrieval/hybrid.py`, `retrieval/recall.py` | Dense + lexical when `hybrid_enabled` |
| Redis vector fields (schema) | `retrieval/rag_route.py` | HNSW field defs for 384-d cosine (does not open Redis alone) |
| Semantic cache | `retrieval/cache.py` | SQLite semantic tier |
| Redis exact cache | `retrieval/redis_exact.py` | Optional; see [REDIS.md](REDIS.md) §8 |
| Mem0 (optional extra) | `pyproject.toml` `[project.optional-dependencies] mem0` | Not required for core RAG path |
| LangGraph handoffs | [LangSwarm.md](LangSwarm.md), `langgraph_swarm` | Context across specialist nodes |
| Memory specialist | [Agents/RAG/AGENTS.md](../Agents/RAG/AGENTS.md) | Retrieval persona; graph memory survey in [RAGTECHNIQUES.MD](RAGTECHNIQUES.MD) §11.1 |

## INDEX

- [Part I — Executive summary & decision flow](#part-i--executive-summary--decision-flow)
- [Part II — Multi-tier agent memory](#part-ii--multi-tier-agent-memory)
  - [2.1 Tiers: short-term, episodic, semantic/graph](#21-tiers-short-term-episodic-semanticgraph)
  - [2.2 Mem0 graph memory APIs](#22-mem0-graph-memory-apis)
  - [2.3 Subagent memory handoff protocols](#23-subagent-memory-handoff-protocols)
  - [2.4 Self-learning feedback loops](#24-self-learning-feedback-loops)
  - [2.5 Python setup (Mem0 example)](#25-python-setup-mem0-example)
  - [2.6 Memory trade-off matrix](#26-memory-trade-off-matrix)
  - [2.7 Memory pitfalls](#27-memory-pitfalls)
- [Part III — Vector store decision workflow](#part-iii--vector-store-decision-workflow)
- [Part IV — Vector engine deep dive](#part-iv--vector-engine-deep-dive)
  - [4.1 LanceDB out-of-core columnar search](#41-lancedb-out-of-core-columnar-search)
  - [4.2 Redis 7.4/8.0 RediSearch VSS](#42-redis-7480-redisearch-vss)
  - [4.3 Qdrant & binary quantization](#43-qdrant--binary-quantization)
  - [4.4 FastEmbed & LangGraph Swarm](#44-fastembed--langgraph-swarm)
- [Part V — Comparison, benchmarks & pitfalls](#part-v--comparison-benchmarks--pitfalls)
- [Part VI — Primary citations](#part-vi--primary-citations)

---

## Part I — Executive summary & decision flow

**Core recommendation:** Adopt a **3-tier memory model** (short-term context, long-term episodic vectors, graph-semantic relationships) with **task-scoped handoffs** so subagents do not inherit full session history. Back episodic and semantic tiers with a vector engine matched to scale and latency (in-memory Redis/Qdrant vs out-of-core LanceDB).

```ascii
[User Interaction]
    |
    v
[Orchestrator Agent] <-----> [Graph + vector memory API]
    |    |   |                   | (semantic retrieval)
    |    |   +------> [Long-Term Episodic store]
    |    |
    |    v (memory handoff — compressed payload)
    |  [Subagent specialists]
    v
[Feedback loop] --> update episodic / graph memory
```

Vector **storage** choice (when episodic tier grows past single-node RAM):

```text
+-------------------------------------------------------------------------+
|                  VECTOR STORE DECISION WORKFLOW                         |
+-------------------------------------------------------------------------+
                                  |
                   [ Evaluate Dataset & Constraint ]
                                  |
            +---------------------+---------------------+
            |                                           |
    [ In-Memory Priority ]                   [ Out-of-Core / Disk ]
    (Sub-millisecond latency)                (TB-scale, zero-copy I/O)
            |                                           |
    +-------+-------+                           +-------+-------+
    |               |                           |               |
[ High Recall ] [ Max Throughput ]         [ Embedded ]    [ Distributed ]
    |               |                           |               |
  Redis VSS     Qdrant (1-bit BQ)            LanceDB      Qdrant (Scalar)
 (HNSW / FLAT)  (SIMD Binarization)         (DiskANN)       (Cloud/Cluster)
    |               |                           |               |
    +---------------+                           +---------------+
            |                                           |
      FastEmbed + LangGraph Swarm (e.g. BAAI/bge-small-en-v1.5)
```

---

## Part II — Multi-tier agent memory

### 2.1 Tiers: short-term, episodic, semantic/graph

- **Short-term memory (context window):** Active turn, orchestrator messages, and in-flight subagent replies. Bounded by model context (128k–1M tokens depending on route).
- **Episodic / long-term memory:** Vectorized interaction logs and summaries so sessions stay coherent without replaying full transcripts.
- **Semantic / graph memory:** Entities and relations (preferences, invariants, dependencies) supporting multi-hop recall beyond pure cosine similarity.

### 2.2 Mem0 graph memory APIs

Mem0 orchestrates **hybrid vector + graph** retrieval: nodes and edges (e.g. `User` → `prefers` → `Python`) contextualize flat embedding hits. In Swarm, treat Mem0 as an **optional** backend when the `mem0` extra is installed; core retrieval remains `swarm_sdk.retrieval`.

### 2.3 Subagent memory handoff protocols

Passing the full orchestrator state to every subagent wastes tokens and invites leakage across roles.

1. **Context compression:** Query memory for task-specific snippets (goal, constraints, prior failures on this task type).
2. **Handoff packaging:** Structured payload — objectives, files, and retrieved memory only.
3. **Return ledger:** Subagent returns a compact action summary; orchestrator commits durable updates to episodic/graph stores.

Align with LangGraph **handoff tools** so `thread_id` / checkpointer state and external memory stay consistent ([LangSwarm.md](LangSwarm.md)).

### 2.4 Self-learning feedback loops

After a task, evaluate outcome (tests pass, user correction, linter clean). Write **corrective facts** to long-term memory (e.g. “flag Y required for dependency X”). Guard with evaluators so bad outcomes are not reinforced ([§2.7](#27-memory-pitfalls)).

### 2.5 Python setup (Mem0 example)

```python
# uv sync --extra mem0  (optional; configure secrets via env / vault — no real passwords in repo)
from mem0 import Memory

m = Memory.from_config({
    "graph_store": {
        "provider": "neo4j",
        "config": {
            "url": "neo4j://localhost:7687",
            "username": "neo4j",
            "password": "password",  # use env in production
        },
    },
    "vector_store": {
        "provider": "redis",
        "config": {"host": "localhost", "port": 6379},
    },
})

m.add(
    "User prefers explicit typing; subagent failed when return types were omitted.",
    user_id="usuario",
    metadata={"feedback_loop": "error_correction", "domain": "python_code"},
)

context = m.search(query="Python typing preferences", user_id="usuario")
```

### 2.6 Memory trade-off matrix

| Capability | Strengths | Weaknesses | Best use case |
| :--- | :--- | :--- | :--- |
| **Vector-only memory** | Fast retrieval, easy to scale | Loses relationship context | Document RAG, session logs |
| **Graph + vector (Mem0-style)** | Entity-aware, relational queries | Graph DB ops burden | Multi-agent orchestration |
| **Summarized handoff** | Token efficient | Risk of dropped constraints | Deep subagent trees |

### 2.7 Memory pitfalls

- **Memory bloat:** Unbounded `add()` without consolidation slows retrieval and adds noise — schedule summarization / TTL policies.
- **Handoff starvation:** Over-compressed handoffs cause hallucination and missed constraints.
- **Feedback loop collapse:** A weak evaluator writes incorrect “lessons” into global memory.

---

## Part III — Vector store decision workflow

See [Part I](#part-i--executive-summary--decision-flow) ASCII workflow. Pair engine choice with [Part V](#part-v--comparison-benchmarks--pitfalls) matrices when sizing RAM and recall targets.

---

## Part IV — Vector engine deep dive

### 4.1 LanceDB out-of-core columnar search

LanceDB builds on **Apache Arrow**, optimizing **out-of-core** search for large corpora.

- **DiskANN / IVF-PQ:** Compressed index in RAM; raw vectors read from disk on demand.
- **Lance columnar format:** Random access oriented (vs sequential Parquet scans).
- **Zero-copy:** Queries can return `pyarrow.Table` views over memory-mapped Lance files, reducing copy overhead on large batches.

### 4.2 Redis 7.4/8.0 RediSearch VSS

In-memory **vector similarity** (module in 7.4, integrated in 8.0).

- **HNSW:** ANN with tunable `EF_RUNTIME` for speed vs recall.
- **FLAT:** Exact search; practical for smaller collections where recall must be exact.
- **Pub/Sub / streams:** Real-time index updates across swarm nodes (mind single-threaded command execution — [§5.3](#53-edge-cases-engine-pitfalls)).

Swarm: Redis also backs **exact semantic cache** when configured ([REDIS.md](REDIS.md) §8); distinguish **cache keys** from **primary vector corpus** indexes.

### 4.3 Qdrant & binary quantization

- **Binary quantization (BQ):** float32 → 1-bit; Hamming distance via SIMD; often paired with oversampling + rescoring.
- **Scalar quantization:** float32 → int8 (~4× RAM savings vs raw floats).
- **Latency:** Aggressive quantization can yield sub-50 ms queries at large scale with tuned rescoring.

### 4.4 FastEmbed & LangGraph Swarm

**FastEmbed** is the compute layer (not storage): ONNX **BAAI/bge-small-en-v1.5** is the common default in this repo’s retrieval stack. LangGraph Swarm agents attach retriever tools; embeddings feed whichever store backs episodic memory ([`retrieval/embeddings.py`](../src/swarm_sdk/retrieval/embeddings.py)).

---

## Part V — Comparison, benchmarks & pitfalls

### 5.1 Engine trade-off matrix

| System | Primary storage | Indexing | Best for | Trade-off |
| :--- | :--- | :--- | :--- | :--- |
| **LanceDB** | Disk / mmap | DiskANN / IVF-PQ | Embedded, TB-scale out-of-core | Higher latency than pure RAM |
| **Redis VSS** | RAM | HNSW / FLAT | Real-time agent memory, strict SLAs | RAM cost at scale |
| **Qdrant BQ** | RAM / disk | HNSW + quant | High throughput, large windows | Recall loss if quant mis-tuned |
| **FastEmbed** | N/A | N/A | CPU embeddings for swarm agents | Not a database |

### 5.2 Feature grid

| Capability | LanceDB | Redis 7.4/8.0 | Qdrant | FastEmbed (Swarm) |
| :--- | :--- | :--- | :--- | :--- |
| **Zero-copy I/O** | Yes (Arrow) | No | No | Yes (NumPy/Arrow) |
| **Storage** | Columnar (Lance) | Key-value | Segmented / graph | Stateless |
| **Hybrid search** | Metadata + vector | TAG/NUMERIC + vector | Payload filters | N/A |
| **Memory sync** | FS / S3 | Pub/Sub / replication | Raft | LangGraph state |

### 5.3 Runtime benchmarks (illustrative)

*Generalized 16-core / 64 GB / NVMe, ~10M × 384-d vectors — not Swarm CI defaults.*

| Metric | LanceDB (IVF-PQ) | Redis VSS (HNSW) | Qdrant (BQ) |
| :--- | :--- | :--- | :--- |
| **RAM (index)** | ~2 GB | ~18 GB (float32) | ~1.5 GB (1-bit + rescore) |
| **Recall @10** | 92% | 98% | 94% (post-rescore) |
| **Indexing throughput** | ~8k vec/s | ~15k vec/s | ~25k vec/s |
| **Query P95** | 15.2 ms | 1.8 ms | 2.5 ms |

### 5.4 Edge cases & engine pitfalls

**Redis — memory bandwidth / event loop:** Heavy VSS queries concurrent with Pub/Sub ingestion can stall the single-threaded command path.

**Qdrant — quantization:** BQ on low-dimensional or unnormalized vectors can drop recall 20–30% without oversampling/rescore.

**LanceDB — I/O:** DiskANN/IVF-PQ need fast random I/O; slow disks negate mmap benefits.

---

## Part VI — Primary citations

### Agent memory

1. [Mem0 documentation](https://docs.mem0.ai/)
2. [Generative Agents (Stanford/Google)](https://arxiv.org/abs/2304.03442)
3. [LangChain multi-agent handoffs](https://python.langchain.com/docs/use_cases/tool_use/agents)

### Vector engines & embeddings

4. [Lance / LanceDB](https://lancedb.com/)
5. [Redis vector search](https://redis.io/docs/latest/develop/interact/search-and-query/advanced-concepts/vectors/)
6. [Qdrant quantization](https://qdrant.tech/documentation/guides/quantization/)
7. [FastEmbed](https://github.com/qdrant/fastembed)
8. [LangGraph](https://github.com/langchain-ai/langgraph)
