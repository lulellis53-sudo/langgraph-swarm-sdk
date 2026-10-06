# Agentic Memory Server on a ThinkPad T430

**Purpose:** a practical design for using a Lenovo ThinkPad T430 with 16 GB DDR3 as a private, always-on memory service for LangGraph Swarm agents. It covers Mem0, Supermemory, Qdrant/vector stores, and handoffs, while distinguishing what this repository supports today from integrations that would need new code.

**Recommendation:** start with the SDK's SQLite-vec store behind a small authenticated API on a wired, private network. Give each agent a private namespace and let handoffs see only explicitly shared memories. Add a remote vector database only when measurements show SQLite is a bottleneck. Do not run a large language model on the T430.

> The hardware has not been benchmarked in this deployment. The proposed batch sizes and retrieval counts below are starting values, not measured performance guarantees. Exact CPU, drive, RAM configuration, and thermal condition vary by T430 unit.

## 1. What the T430 can reasonably host

Lenovo's T430 platform specification lists up to 16 GB of 1600 MHz DDR3 across two SO-DIMM slots. Some configurations use a dual-core mobile i5; verify the installed CPU and drive before sizing concurrency. Put the database on a healthy SSD, keep free disk space for SQLite WAL and backups, and use wired Ethernet. Treat the machine as a small CPU server for API, metadata, embeddings, and vector retrieval—not as a multi-user model-inference host.

With 16 GB RAM, leave memory for Linux, filesystem cache, the API, and embedding/reranking models. Avoid running a model server, browser automation, and several databases together. Prefer one source of truth and one vector index. Keep model generation on a stronger host or a trusted provider; if embeddings are remote, send only the text intended for memory and account for network availability and data policy.

### Suggested first deployment

| Component | Initial choice | Why |
| --- | --- | --- |
| Host OS | Maintained 64-bit Linux distribution | Current package and security updates; verify support for the exact install image and T430 hardware. |
| Long-term memory | SDK `sqlite-vec` on local SSD | Already the SDK default; simplest single-host starting point. |
| Embeddings | Existing `fastembed` backend, 384 dimensions | Matches the repository default model/config; measure CPU latency before enabling concurrency. |
| Conversation checkpoint | Separate durable LangGraph checkpoint store | Thread state and long-term facts have different retention and access needs. |
| API | Authenticated service bound to loopback, behind private TLS gateway | The SDK's current HTTP API is not an agent-scoped memory gateway. Add authorization before exposing it to agents. |
| Generation | Existing remote or separate model host | Preserves the T430's CPU and memory for retrieval and API work. |

## 2. Repository support and integration gaps

The current `MemoryStore` contract in `src/swarm_sdk/memory/base.py` only adds text with a vector and searches by vector. It has no tenant, namespace, ACL, delete, or metadata arguments. `SwarmSDK` recalls before routing and saves a shortened question/answer after a run; that memory belongs to the SDK instance, not a specific specialist. The current HTTP service exposes `/v1/runs`, `/v1/recall`, and health routes, but it does not authenticate or offer scoped memory write/delete endpoints. Do not expose it directly to untrusted networks.

Backends currently include SQLite-vec, FAISS, Qdrant, OpenCL, and Mem0. Important limitations:

- **SQLite-vec:** local SQLite database; appropriate for a single-host prototype. Keep the database on local storage, not NFS or a shared network mount.
- **Qdrant adapter:** `src/swarm_sdk/memory/qdrant_store.py` creates an embedded local Qdrant client from a filesystem path. It does not currently connect to a remote Qdrant URL or filter by agent/tenant. A Qdrant server deployment requires an adapter change.
- **Mem0 adapter:** `src/swarm_sdk/memory/mem0_store.py` uses the Mem0 Platform client and an API key. It is not a connector to the Mem0 OSS self-hosted server. Its current search path is not agent-scoped consistently; review/fix that before using it for isolated agents.
- **Supermemory:** no backend is currently implemented in this repository. Its self-hosted server can be evaluated as an alternative memory service, but requires a client/adapter and authorization integration.

The SDK's LangGraph checkpointer should hold thread state. The memory service should hold selected long-term facts, summaries, and references. Do not use one as a substitute for the other.

## 3. Private-by-default memory model

Use an identity tuple for every record:

```text
tenant_id / workspace_id
owner_agent_id
visibility = private | shared
memory_id, text, vector, embedding_model/version
thread_id, source, created_at, expires_at, tags
```

The API gateway must derive `tenant_id` and permitted `agent_id` from the authenticated credential or a trusted workload identity. Never accept caller-supplied identity as proof of authorization, and never let model output choose its own memory scope. Default writes to `private`. A separate, explicit capability grants access to a tenant's `shared` namespace. For cross-agent handoffs, pass the trusted tenant/thread context and a compact, approved summary or memory IDs; do not forward another agent's private history.

Recommended API contract for a future memory gateway:

```text
POST   /v1/memories          write for the authenticated agent
POST   /v1/memories/search   search private plus authorized shared scope
GET    /v1/memories/{id}     read only when ACL permits
DELETE /v1/memories/{id}     delete only when ACL permits
GET    /healthz              liveness only; no secrets or memory content
```

Example request body (identity is deliberately absent):

```json
{
  "text": "The project uses SQLite-vec for its first local memory deployment.",
  "visibility": "private",
  "thread_id": "thread-opaque-id",
  "tags": ["deployment", "decision"]
}
```

On search, cap `top_k` server-side (start at 10), apply the authenticated tenant/agent filter before ranking, and return only fields the caller may read. Use separate per-agent API credentials or a gateway that maps service identity to scopes. Give handoff targets read permission only for explicitly shared memories. Add rate limits, request size limits, retention/expiry, export/delete support, and audit events that omit memory text and credentials.

### Handoff flow

1. The ingress authenticates the caller and creates trusted `tenant_id`, `user_id`, and `thread_id` context.
2. The active graph node receives only its own private scope plus the tenant's shared scope if authorized.
3. A handoff carries the trusted context and a short, purpose-built summary. It does not carry unrestricted memory search results or another agent's full transcript.
4. The receiving agent searches its own private scope and authorized shared scope independently.
5. The service records the source agent, destination, and sharing decision in metadata/audit logs.

The current outer `SwarmSDK.run()` memory hook cannot implement this per-agent behavior by itself. Add memory tools or node wrappers bound to the executing agent, or add a memory gateway/tool layer to the graph. Keep authorization outside the LLM prompt.

## 4. Starting configuration

The repository's `Settings` uses the `SWARM_` environment prefix. Start with the built-in local backend and a persistent path outside the repository. Set paths and permissions for the Linux account that runs the service.

```dotenv
SWARM_API_HOST=127.0.0.1
SWARM_API_PORT=8000
SWARM_MEMORY_BACKEND=sqlite-vec
SWARM_MEMORY_PATH=/var/lib/swarm/memory.sqlite
SWARM_EMBED_BACKEND=fastembed
SWARM_EMBED_DIM=384
SWARM_EMBED_BATCH_SIZE=8
SWARM_RETRIEVE_K=10
SWARM_RERANK_K=4
```

These values fit the existing settings names. `embed_batch_size=8`, retrieval `top_k=10`, and rerank `k=4` are conservative tuning starting points for a CPU-only host; reduce them if p95 latency or memory pressure is high. Confirm that the configured embedding model produces exactly 384 dimensions. Changing model or dimensions requires a planned re-embedding/reindex, not just an environment change.

Run the API on loopback behind a private reverse proxy or VPN gateway that enforces TLS and authentication. The SDK's existing `/v1/recall` endpoint has no per-agent scope, so it is not itself the memory API described above. Implement the scoped gateway separately or extend the service with authenticated routes and storage filters before connecting agents. Do not publish ports 8000, 50051, or a vector DB port directly to the public internet; the current gRPC path is not an authenticated tenant boundary.

For SQLite operations, use a dedicated service account, restrictive directory permissions, regular encrypted backups, and a tested restore procedure. Monitor disk headroom because database, FTS index, WAL, and backups all consume space. SQLite WAL is useful for local reader concurrency, but writes still serialize; measure contention before increasing workers.

## 5. Choosing Mem0, Supermemory, or Qdrant

Choose one primary long-term store first. Avoid writing the same memories independently to Mem0, Supermemory, and Qdrant unless you have a deliberate replication, deletion, and reconciliation design.

### Mem0

Mem0 offers both a hosted Platform and an open-source self-hosted option. The repository adapter currently targets the **hosted Platform** using `MEM0_API_KEY`, so records leave the T430 and depend on that service. The self-hosted Mem0 server is a separate deployment path; current official docs describe a Docker-based server and default model/vector components. Configure local model/embedding components explicitly if data must stay on your LAN. The OSS stack is heavier than the SDK's SQLite starting point, so check CPU/RAM and measure it before co-hosting on a 16 GB T430.

Use Mem0 filters with care: identity fields and filter combination semantics affect which records are visible. Test actual write/search behavior for private and shared cases. Do not assume filtering by both `user_id` and `agent_id` returns records unless the write path stores both fields on those records. Fix and test the repository adapter's scoping before enabling it for multiple agents.

### Supermemory

Supermemory's self-host quickstart documents a Linux x64 server, local state directory, local embedding option, bearer-token API, and container tags for namespace isolation. A reasonable evaluation layout is a deterministic private tag such as `tenant:<opaque-id>:agent:<agent-name>` and a distinct shared tag such as `tenant:<opaque-id>:shared:<workspace>`. Scope credentials to permitted tags where supported, keep the service private, and test isolation. It is not yet integrated into this SDK; implement an adapter and map its tags from authenticated identity, never from caller text. Check first-run model/key requirements and embedding model resource needs for the chosen release.

### Qdrant

Qdrant is a good next step if measured load, filtering, or operational needs exceed a local SQLite store. Use a pinned image version, persistent local SSD storage, API key authentication, and TLS/private network access. Keep collection design tenant-aware with payload filters; Qdrant's production guidance favors payload-based partitioning over creating one collection per tenant. Quantization may reduce vector RAM/storage, but validate recall and latency on a representative corpus before enabling it. The repository's current Qdrant adapter is embedded/path-based; add and test remote URL, credentials, and mandatory tenant filters before using a Qdrant server.

## 6. Capacity and performance plan

For a rough storage estimate only, 384-dimensional int8 vectors consume about 384 bytes each before metadata and index overhead: roughly 38 MB per 100,000 vectors or 384 MB per million. At an average text size of 1 KB, raw text adds about 100 MB per 100,000 records or 1 GB per million, before FTS/index/WAL overhead. These figures are arithmetic estimates, not observed database sizes. Real payloads, indexing, and vector configuration change the result.

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
| Cost/data | embedding and generation tokens/cost if remote; bytes sent to each external provider |

Set acceptance limits from actual agent response needs (for example a p95 budget agreed by the application owner); do not claim a throughput target until this machine has been measured. Compare SQLite-vec and a Qdrant candidate with the same corpus, embedding model, filters, and quality test set.

## 7. Operations and security checklist

- Bind internal services to loopback or a private interface; front them with VPN/private ingress and TLS.
- Require authentication and server-side tenant/agent authorization on every read and write. Test that Agent A cannot read Agent B's private memory and that shared reads require explicit grants.
- Keep tokens in a secret manager or owner-only environment file; docs and committed YAML contain variable names only.
- Do not log memory contents, bearer tokens, or raw prompts. Log request IDs, scope IDs, action, result count, latency, and denial reason.
- Apply body/top-k limits, quotas, retention, export, deletion, and key rotation.
- Keep the data directory and backups outside the repository. Encrypt backups and regularly test restore on a separate path.
- Monitor disk, RAM, CPU, database/WAL growth, API errors, p95 latency, and the host's thermal state.
- Document embedding model and dimensions with each index. Rebuild or migrate deliberately when changing them.
- Keep thread checkpoints separate from durable memory and choose retention for each independently.

## 8. Primary references

- [Lenovo ThinkPad T430 PSREF](https://psref.lenovo.com/syspool/Sys/PDF/withdrawnbook/ThinkPad_T430_WE.pdf) — platform memory limits and specifications.
- [Mem0 open-source overview](https://docs.mem0.ai/open-source/overview) — library/self-host choices and default components.
- [Mem0 memory filters](https://docs.mem0.ai/platform/features/v2-memory-filters) — identity and filtering behavior.
- [Supermemory self-host quickstart](https://github.com/supermemoryai/supermemory/blob/main/apps/docs/self-hosting/quickstart.mdx) — local server, storage, API, embeddings.
- [Supermemory container tags](https://github.com/supermemoryai/supermemory/blob/main/apps/docs/concepts/container-tags.mdx) — namespace model.
- [Qdrant production checklist](https://qdrant.tech/documentation/production-checklist/) — deployment, security, storage, and quantization considerations.

## 9. Implementation sequence

1. Install and patch a maintained Linux system; confirm CPU, SSD health, RAM, network, and thermals.
2. Deploy the existing SQLite-vec SDK backend on local SSD and collect a baseline with the benchmark matrix.
3. Implement an authenticated memory gateway with server-derived tenant/agent scopes and private-by-default access.
4. Bind memory search/write tools to each graph node; pass only approved shared summaries through handoffs.
5. Add isolation, deletion, expiry, restore, and load tests before connecting real agent credentials.
6. Compare Mem0 OSS, Supermemory, or remote Qdrant only if a concrete requirement or measured bottleneck justifies the added service. Reuse the same authorization and benchmark suite for each candidate.

This is a deployment and integration plan, not an implemented feature or a benchmark report. The current SDK needs scoped storage/API changes before it can safely provide each agent with isolated memory.
