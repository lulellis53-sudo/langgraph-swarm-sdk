# Enterprise Redis 7.4 / 8.0 Architecture & Swarm Integration Manual (2026 Edition)

> **CANONICAL REDIS & CACHING MANUAL** (merged `CACHING.md`, `redis-cache.md`):
> Enterprise Redis 7.4 / 8.0 topology, RediSearch vector indexing, Streams, Redlock, tuning,
> Python `redis.asyncio` patterns, **multi-tier caching architecture**, and **Swarm SDK optional
> exact-response cache** (`REDIS_URL` / `SWARM_REDIS_URL`).

---

## How to use this document

| Section | Audience | Content |
| :--- | :--- | :--- |
| **§1–§7** | Operators / platform | Redis Stack deployment, VSS, Streams, locks, tuning, Docker |
| **§8** | Swarm / WebSearch developers | In-repo `RedisExactCache`, env vars, failure modes, benchmarks |
| **§9** | Architects | Multi-tier cache routing (exact, semantic, columnar, SQLite WAL) |

---

## 1. Executive Architecture Overview & Topology (2026 Standard)

Redis 7.4 and 8.0 serve as the high-performance, ultra-low-latency memory plane for multi-agent swarm operations. This section details production topologies, persistence engines, and memory eviction policies.

### A. Deployment Topology & Containerization
- **Container Image**: `redis/redis-stack-server:latest` or `redis:8.0-alpine` compiled with `mimalloc` allocator.
- **Resource Allocations**: Dedicated CPU pinning (`cpuset`) and non-root execution (`USER redis`).
- **Memory Ceiling**: Configure `maxmemory` explicitly (e.g. `maxmemory 4gb`) to prevent host OOM killer invocation.

### B. Dual Engine Persistence (MP-AOF + RDB)
- **Multi-Part AOF (MP-AOF)**: Redis 7.4+ splits append-only logging into base files, incremental files, and manifest files. Eliminates AOF rewrite memory spikes (`appendfsync everysec`).
- **RDB Snapshots**: Point-in-time binary snapshots configured via `save 900 1 300 10 60 10000` for cold backups.

### C. Eviction Policies for Swarm Memory Layers
- **Semantic Caching & RAG**: `allkeys-lru` or `allkeys-lfu` (evicts least recently/frequently used keys when `maxmemory` is hit).
- **Task Queues & State Locks**: `noeviction` (returns error on writes when memory limit is reached, protecting active queue streams and locks from truncation).

---

## 2. RediSearch Vector Indexing & Hybrid Search (FP16 / INT8 Quantization)

Redis Vector Search enables microsecond-level approximate nearest neighbor (ANN) retrieval for `fastembed` (`BAAI/bge-small-en-v1.5`) and LLM context vectors.

### A. Indexing Topologies: HNSW vs. FLAT
- **HNSW (Hierarchical Navigable Small World)**:
  - Microsecond latency ($O(\log N)$ complexity).
  - Recommended configuration: `M=16`, `EF_CONSTRUCTION=200`, `EF_RUNTIME=100`.
- **FLAT**: Exact brute-force search ($O(N)$ complexity). Recommended only for small, highly dynamic working sets ($N < 10,000$).

### B. Vector Quantization (Redis 7.4+ / 8.0)
- **FLOAT32** (Default): 4 bytes per dimension.
- **FLOAT16**: 2 bytes per dimension (50% memory reduction with negligible recall drop).
- **INT8**: 1 byte per dimension (75% memory reduction with scalar quantization).

### C. Hybrid Search Schema
Combining Full-Text metadata filtering (`TextField`, `TagField`) with dense Vector distance query (`VectorField`):

```redis
FT.CREATE agent_memory_idx ON HASH PREFIX 1 mem:
  SCHEMA
    agent_role TAG
    timestamp NUMERIC
    content TEXT
    embedding VECTOR HNSW 6
      TYPE FLOAT32
      DIM 384
      DISTANCE_METRIC COSINE
      M 16
      EF_CONSTRUCTION 200
```

---

## 3. Redis Streams Task Queue Dispatcher & Consumer Groups

For durable, asynchronous multi-agent task dispatching, **Redis Streams** (`XADD`, `XREADGROUP`, `XAUTOCLAIM`) provide fault-tolerant message delivery.

### A. Core Stream Operations
- **Task Enqueue (`XADD`)**:
  ```redis
  XADD swarm_task_queue MAXLEN ~ 10000 * task_id "task-001" role "compilator" prompt "Compile AVX2 ThinLTO"
  ```
- **Consumer Group Creation (`XGROUP`)**:
  ```redis
  XGROUP CREATE swarm_task_queue swarm_workers $ MKSTREAM
  ```
- **Task Consumption (`XREADGROUP`)**:
  ```redis
  XREADGROUP GROUP swarm_workers worker-node-1 COUNT 1 BLOCK 2000 STREAMS swarm_task_queue >
  ```
- **Task Acknowledgment (`XACK`)**:
  ```redis
  XACK swarm_task_queue swarm_workers 1728140000000-0
  ```
- **Auto-Claiming Stuck Workers (`XAUTOCLAIM`)**:
  Recovers unacknowledged tasks from dead worker nodes after min-idle threshold (e.g. 60,000 ms).

---

## 4. Redlock Distributed State Synchronization Protocol

When concurrent subagents compete for shared workspace resources (e.g. LLM API rate limits, file system mutations, or database schema updates), the **Redlock** protocol guarantees mutual exclusion across distributed nodes.

### A. Single-Node Lock Acquisition
```redis
SET lock:workspace:compilator "worker_uuid_9921" NX PX 30000
```
- `NX`: Only set if key does not exist.
- `PX 30000`: Expire key after 30,000 milliseconds (auto-release safety valve).

### B. Atomic Lock Release (Lua Script)
Prevents a slow agent from accidentally releasing a lock acquired by a newer agent:
```lua
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
```

---

## 5. Microsecond Latency Tuning & Host Kernel Optimization

### A. Host OS Kernel Parameters (`/etc/sysctl.conf`)
```ini
net.core.somaxconn = 65535
vm.overcommit_memory = 1
net.ipv4.tcp_keepalive_time = 300
net.ipv4.tcp_max_syn_backlog = 65535
```

### B. Disable Transparent Huge Pages (THP)
THP creates memory latency spikes during AOF rewrites and fork calls:
```bash
echo never > /sys/kernel/mm/transparent_hugepage/enabled
```

### C. Redis Configuration Tuning (`redis.conf`)
```ini
maxmemory 4gb
maxmemory-policy allkeys-lru
io-threads 4
io-threads-do-reads yes
tcp-backlog 65535
timeout 0
tcp-keepalive 300
```

---

## 6. Complete Python 3.15 `redis.asyncio` Integration Snippets

```python
#!/usr/bin/env python3
"""Enterprise Redis 7.4 / 8.0 Async Integration for Multi-Agent Swarms."""

import asyncio
import json
import numpy as np
import redis.asyncio as redis
from redis.commands.search.field import VectorField, TextField, TagField
from redis.commands.search.indexDefinition import IndexDefinition, IndexType
from redis.commands.search.query import Query


class SwarmRedisClient:
    """Async Redis Client for Vector Search, Streams, and Redlock."""

    def __init__(self, host: str = "localhost", port: int = 6379) -> None:
        self.r = redis.Redis(host=host, port=port, decode_responses=False)

    async def init_vector_index(self) -> None:
        """Creates HNSW Vector Search Index if not present."""
        index_name = "agent_memory_idx"
        try:
            await self.r.ft(index_name).info()
        except redis.ResponseError:
            schema = (
                TagField("agent_role"),
                TextField("content"),
                VectorField("embedding", "HNSW", {
                    "TYPE": "FLOAT32",
                    "DIM": 384,
                    "DISTANCE_METRIC": "COSINE",
                    "M": 16,
                    "EF_CONSTRUCTION": 200,
                })
            )
            definition = IndexDefinition(prefix=["mem:"], index_type=IndexType.HASH)
            await self.r.ft(index_name).create_index(schema, definition=definition)

    async def add_vector_memory(self, memory_id: str, content: str, role: str, vector: list[float]) -> None:
        """Stores vector memory record into Redis Hash."""
        vec_bytes = np.array(vector, dtype=np.float32).tobytes()
        key = f"mem:{memory_id}"
        await self.r.hset(key, mapping={
            "content": content,
            "agent_role": role,
            "embedding": vec_bytes,
        })

    async def search_vector_memory(self, query_vector: list[float], top_k: int = 3) -> list[dict]:
        """Performs K-Nearest Neighbor HNSW vector similarity search."""
        query_vec_bytes = np.array(query_vector, dtype=np.float32).tobytes()
        q = (
            Query(f"*=>[KNN {top_k} @embedding $vec AS score]")
            .sort_by("score")
            .return_fields("content", "agent_role", "score")
            .dialect(2)
        )
        res = await self.r.ft("agent_memory_idx").search(q, query_params={"vec": query_vec_bytes})
        
        results = []
        for doc in res.docs:
            results.append({
                "id": doc.id,
                "content": getattr(doc, "content", ""),
                "role": getattr(doc, "agent_role", ""),
                "score": float(getattr(doc, "score", 0.0)),
            })
        return results

    async def enqueue_stream_task(self, task_id: str, role: str, prompt: str) -> str:
        """Pushes a task into Redis Stream task queue."""
        res = await self.r.xadd("swarm_task_queue", {
            "task_id": task_id,
            "role": role,
            "prompt": prompt,
        }, maxlen=10000, approximate=True)
        return res.decode("utf-8") if isinstance(res, bytes) else str(res)


# ------------------------------------------------------------------------------
# Example Execution
# ------------------------------------------------------------------------------
async def main() -> None:
    client = SwarmRedisClient()
    await client.init_vector_index()
    
    # Store dummy vector memory
    dummy_vec = [0.01 * i for i in range(384)]
    await client.add_vector_memory("mem-001", "Compiled Zsh AVX2 with ThinLTO", "compilator", dummy_vec)
    
    # Search memory
    memories = await client.search_vector_memory(dummy_vec, top_k=1)
    print("Retrieved Vector Memory:", json.dumps(memories, indent=2))
    
    # Push Stream Task
    stream_id = await client.enqueue_stream_task("task-101", "compilator", "Compile Zsh with Mimalloc")
    print(f"Pushed Task Stream ID: {stream_id}")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 7. Production Docker Compose Configuration (`docker/compose.yaml`)

```yaml
version: '3.8'

services:
  redis:
    image: redis/redis-stack-server:latest
    container_name: swarm-redis
    restart: always
    ports:
      - "6379:6379"
      - "8001:8001"  # Redis Insight GUI
    environment:
      - REDIS_ARGS=--maxmemory 4gb --maxmemory-policy allkeys-lru --io-threads 4 --tcp-backlog 65535
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 4G
        reservations:
          cpus: '1.0'
          memory: 2G
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5
    volumes:
      - redis-data:/data

volumes:
  redis-data:
    driver: local
```

---

## 8. Swarm SDK optional exact cache (project integration)

This section documents **what this repository actually ships**. It supersedes the
standalone `redis-cache.md` note. Redis is **optional**: without a URL, Swarm keeps
SQLite exact + semantic caching locally; WebSearch uses its process-local cache.

### 8.1 Enable

```bash
uv sync --extra redis
export REDIS_URL=redis://127.0.0.1:6379/0
# Swarm also accepts:
export SWARM_REDIS_URL=redis://127.0.0.1:6379/0
export SWARM_REDIS_CACHE_TTL_S=86400   # default 1 day; see Settings.redis_cache_ttl_s
```

The application does **not** start or manage a Redis server. Point the URL at a
service you operate (Docker §7, managed cloud, or local `redis-stack-server`).

### 8.2 Behavior (`swarm_sdk.retrieval.redis_exact.RedisExactCache`)

| Invariant | Value / rule |
| :--- | :--- |
| **Namespaces** | `swarm:response` (Swarm `SemanticCache` exact layer); `websearch:results` (WebSearch, default TTL **300 s**, overridable via `cache_ttl_s`) |
| **Key shape** | `{namespace}:v1:{sha256(utf8 logical key)}` — prompts/queries are not stored as Redis key names |
| **Value limit** | **256 KiB** per entry (`_MAX_VALUE_BYTES`); larger responses are not written |
| **Pool / timeouts** | Max **8** connections; **100 ms** connect and command socket timeouts |
| **Errors** | Treated as cache miss or dropped write (debug log only); core paths continue |
| **Semantic layer** | **Local SQLite only** — Redis does not store embeddings or run vector ANN (avoids Redis RAM for vectors) |

`SemanticCache` (`src/swarm_sdk/retrieval/cache.py`) checks Redis for exact hits first,
then SQLite exact, then local semantic cosine search. Settings: `redis_url` aliases
`REDIS_URL`, `SWARM_REDIS_URL` (`src/swarm_sdk/config/settings.py`).

LangGraph Server graph factories build a Redis-enabled cache when those env vars are set
(`src/swarm_sdk/server/graphs.py`).

### 8.3 Security and operations

- Cached values may contain **agent task output** — use ACLs, TLS, and a trusted network.
- Configure server-side **`maxmemory`** and **`maxmemory-policy`** (§1.C); the client cap is per-entry, not total RSS.
- For cross-process reuse, Redis helps; a single worker may still be faster on a local SQLite hit.

### 8.4 Measure (repo harness)

```bash
uv sync --extra redis
REDIS_URL=redis://localhost:6379/0 PYTHONPATH=Agents:. \
  uv run python Agents/benchmark/Tasks/redis_cache/benchmark_redis_cache.py --write-results
uv run pytest Agents/benchmark/Tasks/redis_cache -q
```

Compare cold miss vs warm hit: p50/p95 lookup latency, provider calls avoided, tokens
saved, CPU, peak RSS. See [Agents/benchmark/README.md](../Agents/benchmark/README.md).

---

## 9. Multi-tier caching architecture (merged reference)

Merged from `CACHING.md`. Use this section to **choose a tier**; use §2 for Redis
Vector Search operations when Redis is your semantic plane.

### 9.1 Decision flow

```text
                          [ Cache query ]
                                |
             +------------------+------------------+
             |                  |                  |
       [Exact string key?] [Semantic / embedding?] [Large columnar blob?]
             |                  |                  |
    [Redis exact §8]     [SQLite semantic +       [PyArrow IPC /
     or SQLite exact]     local HNSW / FAISS]       shared memory]
             |                  |                  |
        optional §2         threshold tuning      zero-copy views
     Redis VSS (ANN)        (Swarm default)       between processes
```

### 9.2 Tier comparison

| Tier / technology | Typical latency | Persistence | Primary use in Swarm |
| :--- | :--- | :--- | :--- |
| In-process LRU / dict | sub-ms | No | Hot paths inside one worker |
| **Redis exact** (`RedisExactCache`) | ~1–5 ms | Optional (AOF/RDB) | Shared **exact** responses across processes (§8) |
| **SQLite WAL** (`cache_path`, semantic DB) | ~5–15 ms | Yes | Default **semantic + exact** cache on disk |
| **Redis VSS / RediSearch** | ~1–5 ms ANN | Optional | Enterprise semantic plane (§2); not required for SDK semantic layer |
| **PyArrow IPC / memory map** | O(1) attach | No | Large record batches between isolated processes |

### 9.3 Semantic vector caching

Multi-tier semantic caching stores embeddings and serves **near-duplicate** prompts via
cosine similarity above a threshold (Swarm default **0.97** in `SemanticCache`). Tier 1:
in-process matrix / OpenCL index when enabled. Tier 2: SQLite `semantic_cache` table.
Optional Tier 3: Redis HNSW (§2) when operating a Redis Stack cluster for RAG at scale.

**Pitfall:** thresholds that are too loose increase false-positive cache hits; tune with
benchmark tasks under `Agents/benchmark/Tasks/token_cache_hit/`.

### 9.4 SQLite WAL persistent state

Swarm cache and memory SQLite files use WAL for concurrent readers/writers:

```python
import sqlite3

conn = sqlite3.connect("swarm-cache.sqlite", check_same_thread=False)
conn.execute("PRAGMA journal_mode=WAL")
```

**Pitfall:** WAL files grow until checkpoint; long-lived agents should monitor disk use.

### 9.5 PyArrow zero-copy buffer caching

For dataframe-scale payloads, prefer Arrow record batches and IPC files/memory maps so
consumers attach without pickling full tables. See [SERIALIZATION.md](SERIALIZATION.md)
and [Python3.15.md](Python3.15.md) §4.1 for columnar context.

### 9.6 Eviction policies (recap)

- **LRU / LFU** (`allkeys-lru`, `allkeys-lfu`): recency- or frequency-biased shared caches (§1.C).
- **noeviction**: protect Streams and lock keys from silent drops when `maxmemory` is hit.

### 9.7 Citations (caching layer)

1. [Redis vector search](https://redis.io/docs/latest/develop/interact/search-and-query/vectors/) — RediSearch / VSS.
2. [SQLite WAL mode](https://sqlite.org/wal.html) — persistent cache files.
3. [Apache Arrow columnar format](https://arrow.apache.org/docs/format/Columnar.html) — zero-copy layouts.
4. In-repo: `src/swarm_sdk/retrieval/cache.py`, `src/swarm_sdk/retrieval/redis_exact.py`.
