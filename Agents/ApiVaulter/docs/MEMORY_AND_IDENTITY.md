# Master Cognitive Memory & System Identity Layer

> **Document Target**: `Agents/ApiVaulter/docs/MEMORY_AND_IDENTITY.md`  
> **Authority**: Swarm `ApiVaulter` Security & Infrastructure Agent  
> **Status**: Verified Production Roster (2026-10-14)  
> **Scope**: Authoritative reference for Swarm's cognitive memory persistence layers, user identity anchors, and System-1 decision engines: **JEV**, **Mem0**, and **Supermemory**.

---

## 1. Cognitive Memory & Identity Architecture

```text
+===================================================================================+
|               SWARM COGNITIVE MEMORY & IDENTITY ARCHITECTURE                      |
+===================================================================================+

  [User / Autonomous Agent Interacting]
                 │
                 ├──► [1. JEV: Sovereign Authority & System-1 Decision Router]
                 │    Role:     Root User Authority & Sub-10ms Routing Engine
                 │    Endpoint: https://api.typesafe.ai (POST /v1/systemone)
                 │    Model:    jev-latest
                 │    Engines:  JevRouter (evaluate_choice, evaluate_score, evaluate_noul)
                 │
                 ├──► [2. Mem0: Long-Term Contextual User & Agent Memory]
                 │    Role:     Continuous user profiling, conversational preferences
                 │    MCP:      mem0 (add-memory, search-memories)
                 │    Endpoint: https://api.mem0.ai/v1
                 │    Format:   Vectorized graph storage by userId & agentId
                 │
                 └──► [3. Supermemory: Persistent Workspace Knowledge & Bookmark Engine]
                      Role:     Project & workspace memory, structured facts, code snippets
                      MCP:      supermemory (supermemory_add, supermemory_search, supermemory_list)
                      Containers: "user" (personal), "project" (workspace), custom tags
```

---

## 2. Directory & Keypoints Matrix

| Component | Category | Canonical Secret Key | macOS Keychain | 1Password Secret Reference | MCP Server & Tools | Official Documentation |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **JEV** | Identity & System-1 Router | `JEV_API_KEY` (fallback `TYPESAFE_API_KEY`) | `swarm/JEV_API_KEY` | `op://Private/swarm.JEV_API_KEY/credential` | Core SDK (`JevRouter`) | [typesafe.ai](https://typesafe.ai) |
| **Mem0** | Long-Term Conversational Memory | `MEM0_API_KEY` | `swarm/MEM0_API_KEY` | `op://Private/swarm.MEM0_API_KEY/credential` | `mem0`<br>• `add-memory`<br>• `search-memories` | [docs.mem0.ai](https://docs.mem0.ai) |
| **Supermemory** | Persistent Project & Bookmark Memory | `SUPERMEMORY_API_KEY` | `swarm/SUPERMEMORY_API_KEY` | `op://Private/swarm.SUPERMEMORY_API_KEY/credential` | `supermemory`<br>• `supermemory_add`<br>• `supermemory_search`<br>• `supermemory_list`<br>• `supermemory_forget` | [supermemory.ai/docs](https://supermemory.ai/docs) |

---

## 3. Detailed Profiles & Technical Specifications

### 1. JEV (Sovereign Authority & System-1 Decision Router)

#### Overview & Role
In Swarm, **JEV** has a dual identity:
1. **Sovereign User Authority**: JEV (the User) governs all system parameters, document templates, hardware benchmark allocations, and agent constraints. Agent guidelines enforce the JEV Override Invariant across all research and planning phases.
2. **System-1 Decision Engine (`JevRouter`)**: A non-autoregressive, sub-10ms neural routing engine. It intercepts plan steps to evaluate safety (`evaluate_noul`), assign dynamic confidence scores (`evaluate_score`), and select candidate agent personas (`evaluate_choice`) without waiting for heavy LLM calls.

#### Keypoint & Credentials
- **Canonical Env Key**: `JEV_API_KEY` (with automatic fallback to `TYPESAFE_API_KEY`)
- **macOS Keychain**: `swarm/JEV_API_KEY`
- **1Password Secret Reference**: `op://Private/swarm.JEV_API_KEY/credential`
- **Base Host**: `https://api.typesafe.ai` (configurable via `JEV_BASE_URL` or `JEV_ENDPOINT`)
- **Model**: `jev-latest`
- **Health Probe Endpoint**: `https://api.typesafe.ai/health`

#### SDK & Core Integration
Built directly into `swarm_sdk.core.jev_router.JevRouter` and `swarm_sdk.core.system_one`:
```python
from swarm_sdk.core.jev_router import JevRouter
from swarm_sdk.vault import get as get_vault_key

# 1. Initialize router with vaulted credentials:
jev_key = get_vault_key("JEV_API_KEY") or get_vault_key("TYPESAFE_API_KEY")
router = JevRouter(endpoint="https://api.typesafe.ai", api_key=jev_key)

# 2. Sub-10ms deterministic agent persona routing:
candidates = ["Coder", "DeepResearch", "Optimizer", "Writer"]
selected_agent = router.evaluate_choice("Refactor memory allocator in C++", candidates)

# 3. Safety gate check:
safety_decision = router.evaluate_noul("rm -rf /")
if not safety_decision.safe:
    print(f"Blocked by JEV gate: {safety_decision.reason}")
```

#### API Usage: Commands & CLI
```bash
# 1. Query System-1 Decision API:
curl -s -X POST https://api.typesafe.ai/v1/systemone \
  -H "Authorization: Bearer $JEV_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "jev-latest",
    "prompt": "Evaluate code change risk",
    "candidates": ["low", "medium", "high"]
  }'

# 2. Inspect vaulted JEV credential via modern CLI:
xh GET https://api.typesafe.ai/health "Authorization: Bearer $JEV_API_KEY"
```

#### Documentation
- Official Portal: [https://typesafe.ai](https://typesafe.ai)
- Swarm SDK Implementation: [`src/swarm_sdk/core/jev_router.py`](file:///Users/usuario/Myworkspace/Agents/src/swarm_sdk/core/jev_router.py)

---

### 2. Mem0 (Long-Term Contextual User & Agent Memory)

#### Overview & Role
Mem0 provides the intelligent memory layer for AI agents. It continuously captures user facts, operational preferences, project constraints, and past decisions across sessions. Rather than stuffing full conversation transcripts into prompts, Mem0 extracts atomic memories, creates vector graph associations, and retrieves only contextually relevant facts.

#### Keypoint & Credentials
- **Canonical Env Key**: `MEM0_API_KEY`
- **macOS Keychain**: `swarm/MEM0_API_KEY`
- **1Password Secret Reference**: `op://Private/swarm.MEM0_API_KEY/credential`
- **Base URL**: `https://api.mem0.ai/v1`
- **Health Probe Endpoint**: `https://api.mem0.ai/v1/memories?limit=1`

#### MCP Usage
Active lazy MCP server `mem0` on this workstation:
- `add-memory`: Adds a new memory item for a given user or agent.
  - `content`: Text snippet or preference to store.
  - `userId`: Identifier (default: `'mem0-mcp-user'`).
- `search-memories`: Searches stored memories via semantic similarity.
  - `query`: Natural language question or search topic.
  - `userId`: Target user or agent ID.

```json
// Add Memory Example
{
  "server": "mem0",
  "tool": "add-memory",
  "arguments": {
    "userId": "usuario",
    "content": "User prefers sccache with ZSTD compression and BORE CPU scheduler on Dual Xeon Broadwell-EP."
  }
}

// Search Memory Example
{
  "server": "mem0",
  "tool": "search-memories",
  "arguments": {
    "userId": "usuario",
    "query": "What are the preferred compiler cache and kernel scheduler settings?"
  }
}
```

#### API Usage: Commands & CLI
```bash
# 1. Store a memory item:
curl -s -X POST https://api.mem0.ai/v1/memories/ \
  -H "Authorization: Token $MEM0_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Keep LibreWolf Desktop app bundle intact."}],
    "user_id": "usuario"
  }'

# 2. Search memories via API:
curl -s -X POST https://api.mem0.ai/v1/memories/search/ \
  -H "Authorization: Token $MEM0_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "LibreWolf app bundle location",
    "user_id": "usuario"
  }'

# 3. Using modern xh CLI:
xh POST https://api.mem0.ai/v1/memories/search/ \
  "Authorization: Token $MEM0_API_KEY" \
  query="Broadwell Xeon kernel flags" user_id="usuario"
```

#### Python Integration
```python
from mem0 import Memory
from swarm_sdk.vault import get as get_vault_key

mem0_key = get_vault_key("MEM0_API_KEY")
m = Memory(api_key=mem0_key)
m.add("Prefers AVX2 optimizations without AVX-512", user_id="usuario")
related_memories = m.search("compiler flags", user_id="usuario")
```

#### Documentation
- Official Portal: [https://mem0.ai](https://mem0.ai)
- Developer Docs: [https://docs.mem0.ai](https://docs.mem0.ai)
- GitHub Repository: [https://github.com/mem0ai/mem0](https://github.com/mem0ai/mem0)

---

### 3. Supermemory (Persistent Workspace Knowledge & Bookmark Engine)

#### Overview & Role
Supermemory is a specialized persistent memory and knowledge engine built for developer assistants and coding agents. It supports scoped memory partitioning using container tags:
- `user`: Global personal memories that persist across all projects.
- `project`: Workspace-specific architectural constraints, file maps, and build steps.
- Custom tags: Subsystem-specific namespaces (e.g. `opencl`, `kernel`, `benchmark`).

#### Keypoint & Credentials
- **Canonical Env Key**: `SUPERMEMORY_API_KEY`
- **macOS Keychain**: `swarm/SUPERMEMORY_API_KEY`
- **1Password Secret Reference**: `op://Private/swarm.SUPERMEMORY_API_KEY/credential`
- **Base URL**: `https://api.supermemory.ai/v1`

#### MCP Usage
Configured as `supermemory` (`user-supermemory` / `plugin-cursor-supermemory-supermemory`) on this workstation:
- `supermemory_add`: Saves information with arguments: `workspaceRoot`, `content`, `container` (`"user"`, `"project"`, `"both"`).
- `supermemory_search`: Queries scoped memories with: `workspaceRoot`, `query`, `container`, `limit`.
- `supermemory_list`: Lists all items in a container.
- `supermemory_forget`: Removes outdated memories by ID.
- `supermemory_profile`: Retrieves user profile summary.
- `supermemory_containers`: Lists active containers.

```json
// Add Workspace Memory Example
{
  "server": "supermemory",
  "tool": "supermemory_add",
  "arguments": {
    "workspaceRoot": "/Users/usuario/Myworkspace/Swarm",
    "content": "Canonical repository root is Swarm/. Sibling folders are git worktrees.",
    "container": "project"
  }
}

// Search Memory Example
{
  "server": "supermemory",
  "tool": "supermemory_search",
  "arguments": {
    "workspaceRoot": "/Users/usuario/Myworkspace/Swarm",
    "query": "worktree lane structure",
    "container": "project",
    "limit": 5
  }
}
```

#### API Usage: Commands & CLI
```bash
# 1. Add knowledge item via Supermemory HTTP API:
curl -s -X POST https://api.supermemory.ai/v1/memories \
  -H "Authorization: Bearer $SUPERMEMORY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Intel i7-9750H has AVX2/FMA and no AVX-512 support.",
    "container": "user"
  }'

# 2. Search scoped project memory:
curl -s -X POST https://api.supermemory.ai/v1/memories/search \
  -H "Authorization: Bearer $SUPERMEMORY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Intel CPU capabilities",
    "container": "user",
    "limit": 3
  }'

# 3. Using modern xh CLI:
xh POST https://api.supermemory.ai/v1/memories/search \
  "Authorization: Bearer $SUPERMEMORY_API_KEY" \
  query="worktree git lanes" container="project" limit:=5
```

#### Documentation
- Official Portal: [https://supermemory.ai](https://supermemory.ai)
- Developer Docs: [https://supermemory.ai/docs](https://supermemory.ai/docs)

---

## 4. Autonomous Memory & Identity Integration in Swarm

1. **JEV Identity Precedence**:
   - Every agent during its initialization and planning phase checks `JevRouter` for policy enforcement and routing safety.
   - User overrides issued by JEV take immediate precedence over static defaults.
2. **Context Persistence Lifecycle**:
   - Before answering complex multi-step questions, agents query `Mem0` (`search-memories`) and `Supermemory` (`supermemory_search`) for established preferences and past architectural decisions.
   - Upon completing significant tasks, agents write summarized findings and system invariants to `Supermemory` (`container="project"`).
3. **Vault Security & Zero-Leak Enforcement**:
   - `ApiVaulter` ensures `JEV_API_KEY`, `MEM0_API_KEY`, and `SUPERMEMORY_API_KEY` are persistently stored in macOS Keychain (`swarm/<NAME>`) and 1Password (`op://Private/swarm.<NAME>/credential`).
   - All memory calls resolve credentials dynamically via `swarm_sdk.vault.get` without writing plaintext keys to configuration files.
