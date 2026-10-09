# Enterprise Database Architectures for Multi-Agent Swarms & LangGraph Integration

> **CANONICAL DOSSIER** (merged `DATABASE.md`, `DB.md`): PostgreSQL + pgvector, SQLite + sqlite-vec, DuckDB analytics, LangGraph persistence.
> Swarm runtime: [`memory/sqlite_vec.py`](../src/swarm_sdk/memory/sqlite_vec.py), [`core/checkpoint.py`](../src/swarm_sdk/core/checkpoint.py), [Memory.md](Memory.md) (vector tiers), [Python3.15.md](Python3.15.md) (free-threading pools).

---

## How to use this document

Use the decision workflow for **where state lives** (shared vs embedded vs analytics). Benchmarks are illustrative (Graviton cloud rig); validate on your deployment. Related vector-engine survey: [Memory.md](Memory.md) Part IV; RAG storage notes: [RAGTECHNIQUES.MD](RAGTECHNIQUES.MD) §15.

## Swarm SDK implementation map

| Concern | Module / config | Notes |
| :--- | :--- | :--- |
| Default memory backend | `Settings` / `MemoryBackend` in `config/loader.py` | Default `sqlite-vec`, path `swarm.sqlite` |
| sqlite-vec store | `memory/sqlite_vec.py` | int8 quantization, FTS5 keyword fallback |
| LangGraph checkpoints | `core/checkpoint.py` | `SqliteSaver` when `langgraph-checkpoint-sqlite` available |
| Semantic cache (SQLite) | `retrieval/cache.py` | Separate from `vec_memories` schema |
| Optional Qdrant | `pyproject.toml` `qdrant` extra | Not default embedded path |
| GPU / index hints | `gpu/report.py` | Reports `sqlite_vec` int8 path |

## INDEX

- [1. Executive overview & decision workflow](#1-executive-architecture-overview--decision-workflow)
- [2. Deep technical breakdown](#2-deep-technical-breakdown)
- [3. Comparative trade-off matrix](#3-comparative-analysis--trade-off-matrix)
- [4. Feature & capability grid](#4-structured-feature--capability-grid)
- [5. Runtime benchmarks](#5-runtime-hardware-benchmarks--performance-deltas)
- [6. Edge cases & pitfalls](#6-edge-cases-failure-modes--autovacuum--mvcc-pitfalls)
- [7. Primary citations](#7-primary-citations--evidence-ledger)

---

## 1. Executive Architecture Overview & Decision Workflow

Multi-agent LangGraph swarms need durable, concurrent storage for checkpoints, shared memory, and vectors. This manual covers **PostgreSQL 17 + pgvector 0.8.0+** (centralized), **SQLite 3.48+ + sqlite-vec** (embedded — Swarm default), and **DuckDB + PyArrow** (telemetry / batch analytics).

### Decision Workflow

```ascii
+---------------------------------------------------+
|               Swarm State & Data Need             |
+---------------------------------------------------+
                         |
      +------------------+------------------+
      |                                     |
[Centralized / Shared]               [Local / Embedded]
      |                                     |
      v                                     v
+------------------------+         +------------------------+
|   PostgreSQL 17 +      |         |     SQLite 3.48+ +     |
|   pgvector 0.8.0+      |         |       sqlite-vec       |
+------------------------+         +------------------------+
| Multi-Agent Shared     |         | Single-Agent Local     |
| Memory & Vector Store  |         | Memory & Edge State    |
| LangGraph DB State     |         | Offline / Ephemeral    |
+------------------------+         +------------------------+
      |                                     |
      +------------------+------------------+
                         |
                         v
               +------------------------+
               |     Data Analytics     |
               |       & Telemetry      |
               +------------------------+
                         |
                         v
               +------------------------+
               |   DuckDB + PyArrow     |
               | Zero-Copy Integration  |
               +------------------------+
               | Batch Swarm Analytics  |
               | Performance Metrics    |
               +------------------------+
```

## 2. Deep Technical Breakdown

### PostgreSQL 17 + pgvector 0.8.0+

PostgreSQL 17 improves concurrent workloads for LangGraph-style coordination. With **pgvector 0.8.0+** and extensions such as **pgvectorscale**, it supports production vector search.

- **Iterative scan tuning:** `strict_order` for exact distance ordering; `relaxed_order` for higher ANN throughput.
- **Memory & scan parameters:** `max_scan_tuples` bounds HNSW traversal depth; `scan_mem_multiplier` keeps hot graph walks in RAM during inference bursts.
- **PgCat pooler:** Multiplexes hundreds of agent connections — routing, pooling, failover — so the primary is not overwhelmed by checkpoint traffic.

### Embedded Engines: SQLite 3.48+ with sqlite-vec

Localized agent state and edge vectors without a network hop. **Swarm** implements this path in `SqliteVecStore` (int8 vectors + FTS5).

- **WAL concurrency:** Readers proceed while a writer commits agent state — required for async LangGraph nodes.
- **sqlite-vec:** Vector distance inside the `.sqlite` file; aligns with default `MemoryBackend = "sqlite-vec"`.

### Columnar Data Engines: DuckDB PyArrow Zero-Copy

Offload swarm telemetry, benchmark aggregates, and state-transition analytics.

- **Zero-copy:** DuckDB scans PyArrow buffers from LangGraph / OTel streams without round-tripping through Pandas.

### LangGraph Swarm State Machine Persistence & Connection Pool Concurrency

- **State persistence:** Checkpoint writes should be atomic; PostgreSQL uses serializable or read-committed policies depending on cross-agent write contention.
- **Python 3.15 free-threading pools:** With the GIL optional, thread-safe pools (`psycopg3`, `sqlite3`, `duckdb`) let multiple agents query in parallel — enforce pool limits to avoid exhaustion ([§6](#6-edge-cases-failure-modes--autovacuum--mvcc-pitfalls)).

## 3. Comparative Analysis & Trade-Off Matrix

| Metric | PostgreSQL 17 + pgvector | SQLite 3.48+ + sqlite-vec | DuckDB + PyArrow |
| :--- | :--- | :--- | :--- |
| **Architecture** | Centralized, client-server | Local, embedded file | Embedded columnar |
| **Concurrency** | High (PgCat multiplexing) | Low–medium (WAL mode) | Read-heavy analytics |
| **Vector search** | Exact / HNSW / IVFFlat | Exact / HNSW (extension) | Not native |
| **State persistence** | Global swarm state | Single-agent / edge state | Ephemeral analysis |
| **Setup complexity** | High | Minimal | Low |
| **Zero-copy Python** | No | No | Yes (PyArrow) |

## 4. Structured Feature & Capability Grid

| Capability | PostgreSQL 17 | SQLite 3.48+ | DuckDB |
| :--- | :--- | :--- | :--- |
| **ACID compliance** | Yes | Yes | Yes |
| **Multi-threaded pooler** | PgCat | Application level | Native threads |
| **Vector indexing** | HNSW, IVFFlat | HNSW (sqlite-vec) | N/A |
| **Network overhead** | TCP/IP latency | Zero (in-process) | Zero (in-process) |
| **High availability** | Streaming replication | File backup / Litestream | N/A |
| **Python 3.15 GIL-free** | psycopg3 (thread-safe) | sqlite3 (thread-safe) | duckdb (thread-safe) |

## 5. Runtime Hardware Benchmarks & Performance Deltas

*Hardware: AWS r7g.4xlarge (Graviton3, 16 vCPU, 128 GiB RAM, io2 NVMe) — not Swarm CI; treat as order-of-magnitude only.*

| Database configuration | Workload | Ops/sec | P50 | P99 | Δ% vs baseline |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **PostgreSQL 17 (baseline)** | State R/W | 24,500 | 1.2 ms | 4.8 ms | 0.0% |
| **PostgreSQL 17 + PgCat** | High concurrency R/W | 42,100 | 0.8 ms | 2.1 ms | +71.8% |
| **pgvector 0.8.0+ (relaxed)** | Vector KNN (1536d) | 12,800 | 3.1 ms | 8.5 ms | +145% (vs 0.7) |
| **SQLite 3.48+ (WAL)** | Local state R/W | 85,000 | 0.2 ms | 1.1 ms | N/A |
| **DuckDB + PyArrow** | Aggregation | N/A | 14.5 ms | 28.0 ms | −85% (vs Pandas) |

## 6. Edge Cases, Failure Modes & Autovacuum / MVCC Pitfalls

- **MVCC bloat:** Frequent short-lived state updates create dead tuples; tune `autovacuum_vacuum_scale_factor` (e.g. `0.01`) on PostgreSQL checkpoint tables.
- **HNSW fragmentation:** Churn on pgvector indexes may require periodic `REINDEX`.
- **SQLite WAL checkpoint starvation:** Long-lived read connections can prevent WAL shrink — close idle readers or run checkpoint policy.
- **Pool exhaustion (3.15 free-threading):** Cap concurrent DB nodes; use timeouts and connection recycling in LangGraph executors.

## 7. Primary Citations & Evidence Ledger

1. **PostgreSQL Global Development Group.** *PostgreSQL 17: Concurrency and MVCC.* https://www.postgresql.org/docs/17/mvcc.html
2. **pgvector Contributors.** *pgvector 0.8.0+ release notes and HNSW tuning.* https://github.com/pgvector/pgvector
3. **PgCat Development Team.** *PgCat connection pooler.* https://github.com/postgresml/pgcat
4. **SQLite Consortium.** *WAL mode.* https://www.sqlite.org/wal.html
5. **sqlite-vec Authors.** *Vector search extension for SQLite.* https://github.com/asg017/sqlite-vec
6. **DuckDB Foundation.** *PyArrow integration.* https://duckdb.org/docs/api/python/pyarrow.html
7. **LangGraph.** *State machine persistence.* https://github.com/langchain-ai/langgraph
8. **Python Software Foundation.** *Python 3.15 what's new (free-threading).* https://docs.python.org/3.15/whatsnew/3.15.html
