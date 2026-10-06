# Agentic Memory Server on a ThinkPad T430

> **Status:** deployment plan with a workstation microbenchmark; no T430 benchmark has been run.
> **Audience:** operator deploying LangGraph Swarm long-term memory on a private host.
> **Evidence:** [`AgenticMemoServer.evidence.json`](AgenticMemoServer.evidence.json) · **Updated:** 2026-10-06
> **Scope:** ThinkPad T430 (16 GB DDR3) as private memory service · Mem0 / Supermemory / Qdrant / handoffs.

**Purpose.** Practical design for using a Lenovo ThinkPad T430 with 16 GB DDR3 as a private,
always-on memory service for LangGraph Swarm agents — covering Mem0, Supermemory,
Qdrant/vector stores, and handoffs — while separating what this repository supports today
from integrations that still need code.

**Recommendation (TL;DR).** Start with the SDK `sqlite-vec` store on local SSD behind a small
authenticated gateway on a wired, private network. Give each agent a private namespace; handoffs
see only explicitly shared memories. Add a remote vector DB only when measurements prove SQLite
is the bottleneck. Do not run LLM generation on the T430.

> Hardware has not been benchmarked in this deployment. Batch sizes and retrieval counts below
> are conservative starting values, not performance guarantees. CPU, drive, RAM, and thermal
> condition vary by T430 unit — measure before sizing concurrency.

## Contents

- [1. What the T430 can reasonably host](#1-what-the-t430-can-reasonably-host)
- [2. Target architecture](#2-target-architecture)
- [3. Repository support and integration gaps](#3-repository-support-and-integration-gaps)
- [4. Private-by-default memory model](#4-private-by-default-memory-model)
- [5. Starting configuration](#5-starting-configuration)
- [6. Choosing Mem0, Supermemory, or Qdrant](#6-choosing-mem0-supermemory-or-qdrant)
- [7. Capacity and performance plan](#7-capacity-and-performance-plan)
- [8. Operations and security checklist](#8-operations-and-security-checklist)
- [9. Implementation sequence](#9-implementation-sequence)
- [10. Primary references](#10-primary-references)

## 1. What the T430 can reasonably host

Lenovo's T430 platform specification lists up to 16 GB of 1600 MHz DDR3 across two SO-DIMM
slots and several dual-core mobile Ivy Bridge CPU options. This is the platform ceiling, not RAM
available to the service: Linux, filesystem cache, and other processes use part of it. Verify the
installed CPU, drive health, and RAM on the individual machine before sizing concurrency. Put the database on a healthy SSD, keep free space for SQLite WAL
and backups, and prefer wired Ethernet. Treat the machine as a small CPU server for API,
metadata, embeddings, and vector retrieval — not as a multi-user model-inference host.

With 16 GB RAM, budget for Linux, filesystem cache, the API process, and embedding/reranker
models. Do not co-host a model server, browser automation, and several databases. Prefer one
source of truth and one vector index. Keep generation on a stronger host or trusted provider;
if embeddings are remote, send only text intended for memory and account for network
availability plus data policy.

### Suggested first deployment

| Component | Initial choice | Why |
| --- | --- | --- |
| Host OS | Maintained 64-bit Linux | Security updates; verify image supports T430 hardware |
| Long-term memory | SDK `sqlite-vec` on local SSD | Repo default (`Settings.memory_backend`); simplest single host |
| Embeddings | `fastembed` backend, 384 dims | Matches `Settings.embed_model` default; measure CPU latency first |
| Conversation checkpoint | Separate durable LangGraph checkpoint store | Thread state vs. long-term facts need different retention/ACLs |
| API | Authenticated gateway on loopback → private TLS/VPN | SDK `/v1/recall` has no auth or per-agent scope — do not expose it |
| Generation | Remote or separate model host | Preserves T430 CPU/RAM for retrieval and API work |

## 2. Target architecture

```text
agents (private LAN/VPN)
   │  mTLS or bearer + per-agent credential
   ▼
┌──────────────┐   server-derived tenant/agent   ┌───────────────────┐
│ memory       │ ───────────────────────────────▶ │ sqlite-vec on SSD │
│ gateway      │   private-by-default ACL filter  │ + FTS5 hybrid     │
│ (new code)   │ ◀─────────────────────────────── │ fastembed 384-dim │
└──────────────┘   top-k, reranked, scoped hits  └───────────────────┘
   │ audit (no text/secrets)          │ WAL + encrypted backups
   ▼                                  ▼
LangGraph swarm nodes          LangGraph checkpointer (separate)
(each node: own scope)         (thread state, not facts)
```

Generation stays off-box. The gateway is the only tenant boundary — the SDK HTTP/gRPC
services are execution APIs, not memory ACLs.

## 3. Repository support and integration gaps

*Verified against repository code on 2026-10-06.*

`MemoryStore` (`src/swarm_sdk/memory/base.py`) only supports `add(text, vector)` and
`search(vector, k)` — no tenant, namespace, ACL, delete, or metadata arguments.
`SwarmSDK` recalls before routing and saves a shortened Q/A after a run; that memory belongs
to the SDK instance, not to a specialist. The HTTP service (`src/swarm_sdk/serving/http.py`)
exposes `POST /v1/runs`, `POST /v1/recall`, `GET /healthz`, and `GET /v1/health` with **no
authentication** and no scoped memory write/delete endpoints. The gRPC service
(`src/swarm_sdk/serving/grpc.py`) is likewise an insecure execution API. Do not expose either
directly to untrusted networks.

| Backend | File | Status for T430 multi-agent use |
| --- | --- | --- |
| `sqlite-vec` | `src/swarm_sdk/memory/sqlite_vec.py` | ✅ Default starting point. Local SQLite + WAL, int8 vectors, FTS5 hybrid (token-scan fallback). Keep DB on local SSD, never NFS. |
| `qdrant` | `src/swarm_sdk/memory/qdrant_store.py` | ⚠️ Embedded/local client only (`QdrantClient(path=…)`). No remote URL, no credentials, no tenant filter. Server use needs adapter work. |
| `mem0` | `src/swarm_sdk/memory/mem0_store.py` | ⚠️ Hosted Platform `MemoryClient` (`MEM0_API_KEY`), not OSS self-host. `add` stores `user_id` + `agent_id`, but `search_text` filters only `user_id` — agent scoping is inconsistent. Fix before multi-agent use. |
| `faiss` / `opencl` | `faiss_store.py` / `opencl_store.py` | Local indexes; no tenancy. Useful for single-tenant benchmarks, not isolation. |
| `supermemory` | — | ❌ No backend in this repo. Evaluate as external service + new adapter. |

Checkpointer (thread state) and memory service (facts/summaries/references) have different
retention and access needs — do not substitute one for the other.

## 4. Private-by-default memory model

Use an identity tuple for every record (gateway-enforced, never caller-supplied):

```text
tenant_id / workspace_id        ← from authenticated credential
owner_agent_id                  ← from authenticated credential
visibility = private | shared   ← default private
memory_id, text, vector, embedding_model/version
thread_id, source, created_at, expires_at, tags
```

The gateway derives `tenant_id` and permitted `agent_id` from the credential or trusted
workload identity. Never accept caller-supplied identity as authorization, and never let model
output choose its own scope. Default writes to `private`; a separate explicit grant opens the
tenant `shared` namespace. For handoffs, pass trusted tenant/thread context plus a compact
approved summary or memory IDs — never another agent's private history.

Recommended gateway contract (new code — not the current SDK routes):

```text
POST   /v1/memories          write for the authenticated agent
POST   /v1/memories/search   search private + authorized shared scope
GET    /v1/memories/{id}     read only when ACL permits
DELETE /v1/memories/{id}     delete only when ACL permits
GET    /healthz              liveness only; no secrets or memory content
```

Example body (identity deliberately absent — server derives it):

```json
{
  "text": "The project uses SQLite-vec for its first local memory deployment.",
  "visibility": "private",
  "thread_id": "thread-opaque-id",
  "tags": ["deployment", "decision"]
}
```

On search: cap `top_k` server-side (start at 10), apply tenant/agent filter **before** ranking,
return only readable fields. Use per-agent credentials or a gateway scope map. Handoff targets
get read access only to explicitly shared memories. Add rate/body/top-k limits, quotas,
retention/expiry, export/delete, and audit events that omit text and credentials.

### Handoff flow

1. Ingress authenticates the caller → trusted `tenant_id`, `user_id`, `thread_id`.
2. Active node sees only its private scope + authorized tenant `shared` scope.
3. Handoff carries trusted context + short purpose-built summary — not raw hits or transcripts.
4. Receiving agent searches its own private + authorized shared scope independently.
5. Service logs source, destination, and sharing decision (metadata only).

The current `SwarmSDK.run()` memory hook cannot do per-agent scoping alone. Add memory tools
or node wrappers bound to the executing agent, plus a gateway/tool layer on the graph. Keep
authorization outside the LLM prompt.

## 5. Starting configuration

`Settings` (`src/swarm_sdk/agents/config/settings.py`) uses the `SWARM_` prefix. Start local,
persist outside the repo, and lock down the service account. All names below map to real
`Settings` fields (`memory_backend`, `memory_path`, `embed_backend`, `embed_model`,
`embed_dim`, `embed_batch_size`, `retrieve_k`, `rerank_k`); values are conservative
CPU-first tuning, not repo defaults (`retrieve_k` defaults to 20, `embed_batch_size` to 64):

```dotenv
SWARM_API_HOST=127.0.0.1
SWARM_API_PORT=8000
SWARM_MEMORY_BACKEND=sqlite-vec
SWARM_MEMORY_PATH=/var/lib/swarm/memory.sqlite
SWARM_EMBED_BACKEND=fastembed
SWARM_EMBED_MODEL=sentence-transformers/all-MiniLM-L6-v2
SWARM_EMBED_DIM=384
SWARM_EMBED_BATCH_SIZE=8
SWARM_RETRIEVE_K=10
SWARM_RERANK_K=4
```

`retrieve_k=10` + `rerank_k=4` (vs. repo defaults 20/4) and `embed_batch_size=8`
(vs. default 64) are conservative CPU-first values — lower further if p95 latency or RSS
climbs. Confirm the model emits exactly 384 dims; changing model/dims needs a planned
re-embedding, not just an env change.

Run the API on loopback behind a private reverse proxy or VPN gateway that enforces TLS and authentication. The SDK's existing `/v1/recall` endpoint has no per-agent scope, so it is not itself the memory API described above. Implement the scoped gateway separately or extend the service with authenticated routes and storage filters before connecting agents. Do not publish ports 8000, 50051, or a vector DB port directly to the public internet; the current gRPC path is not an authenticated tenant boundary.

For SQLite operations, use a dedicated service account, restrictive directory permissions, regular encrypted backups, and a tested restore procedure. Monitor disk headroom because database, FTS index, WAL, and backups all consume space. SQLite WAL is useful for local reader concurrency, but writes still serialize; measure contention before increasing workers.

## 6. Choosing Mem0, Supermemory, or Qdrant

Choose one primary long-term store first. Avoid writing the same memories independently to Mem0, Supermemory, and Qdrant unless you have a deliberate replication, deletion, and reconciliation design.

| Option | Choose when | Cost on a 16 GB T430 |
| --- | --- | --- |
| `sqlite-vec` (default) | Single-host pilot; measured workload fits the available disk and latency budget | Lowest: one SQLite file + local FastEmbed |
| Qdrant server | Filters/concurrency exceed SQLite, or Qdrant is already operated elsewhere | Medium: extra service + RAM/disk; needs remote-URL/auth adapter |
| Mem0 OSS self-host | Mem0 extraction/graph semantics are a hard requirement, running locally | Highest: LLM + embedder + vector stack on 16 GB — measure first |
| Mem0 Platform | Records may leave the LAN for hosted memory | Off-box data + `MEM0_API_KEY`; fix agent scoping first |
| Supermemory self-host | Its tag-namespace + bearer-token model fits your ops | Medium: extra service; needs a new SDK adapter |

### Mem0

Mem0 offers both a hosted Platform and an open-source self-hosted option. The repository adapter currently targets the **hosted Platform** using `MEM0_API_KEY`, so records leave the T430 and depend on that service. The self-hosted Mem0 server is a separate deployment path; current official docs describe a Docker-based server and default model/vector components. Configure local model/embedding components explicitly if data must stay on your LAN. The OSS stack is heavier than the SDK's SQLite starting point, so check CPU/RAM and measure it before co-hosting on a 16 GB T430.

⚠️ Scoping bug: `add` stores both `user_id` and `agent_id`, but `search_text` filters only
on `user_id` (`mem0_store.py`). Do not assume combined `user_id` + `agent_id` filtering
isolates agents until the search path enforces both. Fix and test private/shared
round-trips before enabling the adapter for multiple agents.

### Supermemory

Supermemory's self-host quickstart documents a Linux x64 server, local state directory, local embedding option, bearer-token API, and container tags for namespace isolation. A reasonable evaluation layout is a deterministic private tag such as `tenant:<opaque-id>:agent:<agent-name>` and a distinct shared tag such as `tenant:<opaque-id>:shared:<workspace>`. Scope credentials to permitted tags where supported, keep the service private, and test isolation. It is not yet integrated into this SDK; implement an adapter and map its tags from authenticated identity, never from caller text. Check first-run model/key requirements and embedding model resource needs for the chosen release.

### Qdrant

Qdrant is a good next step if measured load, filtering, or operational needs exceed a local SQLite store. Use a pinned image version, persistent local SSD storage, API key authentication, and TLS/private network access. Keep collection design tenant-aware with payload filters; Qdrant's production guidance favors payload-based partitioning over creating one collection per tenant. Quantization may reduce vector RAM/storage, but validate recall and latency on a representative corpus before enabling it. The repository's current Qdrant adapter is embedded/path-based; add and test remote URL, credentials, and mandatory tenant filters before using a Qdrant server.

## 7. Capacity and performance plan

For a rough storage estimate only, this repository quantizes 384-dimensional vectors to int8, or about 384 bytes per vector before SQLite rows, text, FTS, indexes, WAL, and filesystem overhead. At an average text size of 1 KB, raw text adds about 100 MB per 100,000 records. These are arithmetic estimates, not observed database sizes — real payloads and indexing change the result:

| Records | Vectors (int8) | Text (~1 KB each) | Notes |
| --- | --- | --- | --- |
| 100k | ~38 MB | ~100 MB | + FTS/index/WAL overhead |
| 500k | ~192 MB | ~500 MB | Watch SSD headroom + backup time |
| 1M | ~384 MB | ~1 GB | Run a representative capacity test before choosing a backend |

These byte counts do not establish a practical record limit. In particular, the 500k and 1M
rows are capacity scenarios to measure, not claims that a T430 can meet a given latency at that
scale. SQLite-vec query latency, text/FTS size, WAL growth, SSD condition, and concurrent writes
must be measured with the actual corpus and embedding configuration.

### Measured local microbenchmark (not a T430 result)

The available benchmark host is a MacBook Pro-class Intel x86_64 machine (Core i7-9750H,
16 GB RAM as reported by the workspace), macOS 26.7.1, CPython 3.14.8. This is useful as a
repeatable code-path check but is not a substitute for running the same workload on the T430.
With the repository's `SqliteVecStore`, native sqlite-vec enabled, a temporary local database,
2,000 deterministic synthetic 384-dimensional vectors, and one commit per insert, the observed
run was:

| Measurement | Observed result |
| --- | ---: |
| Insert throughput | 1,189 records/s |
| Search, k=10, 30 sequential queries, p50 | 1.76 ms |
| Search, k=10, 30 sequential queries, p95 (nearest-rank estimate) | 1.91 ms |
| 50 searches using 1 / 5 / 10 caller threads | 0.081 / 0.082 / 0.075 s |

These are one-run microbenchmark observations, not service-level guarantees. They omit embedding
generation, network/API time, realistic text lengths, restart/recovery, long-running WAL growth,
thermal soak, and competing workloads. The store also uses a process-local lock around its SQLite
connection, so the thread-count row measures this implementation's serialized connection path;
it does not show that SQLite or a multi-process deployment scales linearly. Repeat warm and cold
runs, report medians and tail latency over several trials, and run on the target T430 SSD before
choosing production concurrency or a capacity ceiling.

The benchmark used seeded Gaussian vectors and synthetic short text, inserted each record through
`SqliteVecStore.add`, then timed `search(vector, 10)` with `time.perf_counter`; p95 is the nearest-rank
estimate from 30 samples. To reproduce it,
run the same fixed seed and workload on the target host, record the Python/SQLite/sqlite-vec
versions, and retain the database on the intended SSD. Do not compare runs that differ in vector
backend, database path type, embedding model, or power/thermal state.

Optimize in this order:

1. Store concise, deduplicated memory summaries rather than whole conversations.
2. Set expiry/retention for transient facts and delete superseded records.
3. Batch embedding writes conservatively; benchmark batch sizes 1, 4, 8, and 16 on the installed CPU.
4. Retrieve a small candidate set, then rerank only the most useful candidates. Begin with 10 retrieved and 4 reranked; tune on relevance labels.
5. Measure embedding time separately from DB search and API time. Cache embeddings only with a key that includes model/version and normalized text.
6. Consider int8/quantization only after measuring relevance impact. Keep source text and model/version metadata so an index can be rebuilt.
7. Move to a Qdrant server only when local measurements show a clear need; do not add operational services speculatively.

### Benchmark matrix

Use a representative, non-sensitive corpus with labeled relevant results. Run 10k, 100k, and (if storage permits) 500k records; test one client and 5/10 concurrent clients. Record:

| Category | Metrics |
| --- | --- |
| Retrieval quality | Recall@5/10, MRR or NDCG@10, duplicate rate, stale-memory rate |
| Latency | p50/p95 for embedding, search, reranking, writes, and end-to-end API |
| Throughput | successful searches/writes per second at each concurrency level; write-lock errors/timeouts |
| Host pressure | CPU utilization, peak RSS, disk bytes for DB/index/WAL, free-space trend, temperature/throttling |
| Operations | restart recovery, backup/restore duration, recovery point, behavior on full disk and provider outage |
| Safety | cross-agent and cross-tenant isolation checks, delete/expiry verification, unauthorized request rejection |
| Data movement | request counts and bytes sent to each external provider; whether remote embedding is enabled |

Set acceptance limits from actual agent response needs (for example a p95 budget agreed by the application owner); do not claim a throughput target until this machine has been measured. Compare SQLite-vec and a Qdrant candidate with the same corpus, embedding model, filters, and quality test set.

## 8. Operations and security checklist

- [ ] Bind internal services to loopback or a private interface; front them with VPN/private ingress and TLS.
- [ ] Require authentication and server-side tenant/agent authorization on every read and write. Test that Agent A cannot read Agent B's private memory and that shared reads require explicit grants.
- [ ] Keep tokens in a secret manager or owner-only environment file; docs and committed YAML contain variable names only.
- [ ] Do not log memory contents, bearer tokens, or raw prompts. Log request IDs, scope IDs, action, result count, latency, and denial reason.
- [ ] Apply body/top-k limits, quotas, retention, export, deletion, and key rotation.
- [ ] Keep the data directory and backups outside the repository. Encrypt backups and regularly test restore on a separate path.
- [ ] Monitor disk, RAM, CPU, database/WAL growth, API errors, p95 latency, and the host's thermal state.
- [ ] Document embedding model and dimensions with each index. Rebuild or migrate deliberately when changing them.
- [ ] Keep thread checkpoints separate from durable memory and choose retention for each independently.

## 9. Implementation sequence

| Step | Action | Done when |
| --- | --- | --- |
| 1 | Install and patch a maintained Linux system; confirm CPU, SSD health, RAM, network, and thermals | Hardware inventory recorded; `smartctl` clean |
| 2 | Deploy the existing SQLite-vec SDK backend on local SSD and collect a baseline with the benchmark matrix | p50/p95 and quality numbers filed for §7 |
| 3 | Implement an authenticated memory gateway with server-derived tenant/agent scopes and private-by-default access | Isolation tests green; `/v1/recall` no longer directly reachable |
| 4 | Bind memory search/write tools to each graph node; pass only approved shared summaries through handoffs | §4 handoff flow verified end-to-end |
| 5 | Add isolation, deletion, expiry, restore, and load tests before connecting real agent credentials | §8 checklist fully checked |
| 6 | Compare Mem0 OSS, Supermemory, or remote Qdrant only if a concrete requirement or measured bottleneck justifies the added service | Same authorization and benchmark suite reused per candidate |

## 10. Primary references

- [Lenovo ThinkPad T430 PSREF](https://psref.lenovo.com/syspool/Sys/PDF/withdrawnbook/ThinkPad_T430_WE.pdf) — platform memory limits and specifications.
- [Mem0 open-source overview](https://docs.mem0.ai/open-source/overview) — library/self-host choices and default components.
- [Mem0 memory filters](https://docs.mem0.ai/platform/features/v2-memory-filters) — identity and filtering behavior.
- [Supermemory self-host quickstart](https://github.com/supermemoryai/supermemory/blob/main/apps/docs/self-hosting/quickstart.mdx) — local server, storage, API, embeddings.
- [Supermemory container tags](https://github.com/supermemoryai/supermemory/blob/main/apps/docs/concepts/container-tags.mdx) — namespace model.
- [Qdrant production checklist](https://qdrant.tech/documentation/production-checklist/) — deployment, security, storage, and quantization considerations.
- [Qdrant capacity planning](https://qdrant.tech/documentation/operations/capacity-planning/) — vector datatype, dimensions, payload/index, and memory-tier sizing.
- [SQLite write-ahead logging](https://www.sqlite.org/wal.html) — reader/writer behavior, checkpointing, and same-host limitation.

---

*This is a deployment and integration plan, not an implemented feature. The measured results above are from the available workstation and are not T430 performance claims. The current SDK needs scoped storage/API changes (§3) before it can safely provide each agent with isolated memory. Source-verification notes live in [`AgenticMemoServer.evidence.json`](AgenticMemoServer.evidence.json).*
