# Tree — workspace map and design workflow

> Main line: **`swarm_sdk`**. Canonical git root: `~/Myworkspace/Swarm`.  
> Sibling folders are **worktrees** of the same object store. A folder name is not proof of the branch checked out there — run `git -C <path> branch --show-current` before any git work.

---

## 1. Workspace tree (lanes)

```
Myworkspace/
├── Swarm/                    [intended: swarm_sdk]   MAIN — src/swarm_sdk + defaults
├── Websearch/                [intended: Websearch]   WebSearch module
│   └── TechNews/             product until TechNews lane owns it
├── Prediction/               [intended: Prediction]  forecast engine
│   └── Prediction/BotDeal/   façade sources
├── BotDeal/                  [intended: BotDeal]     deal-hunting product
├── Modules/
│   ├── Newsletter/           [intended: newsletter]
│   ├── TechNews/             [intended: TechNews]
│   └── BotDeal/              feat/botdeal-modules (integration alias)
├── Agents/                   [intended: Agents]      personas + benchmarks
├── WebScraper/               scraper lane (if active)
├── RefactorOpenCL/           shared OpenCL helpers
├── AGENTS.md                 lane map (this machine)
└── Myworkspace.code-workspace
```

```
swarm_sdk  ← MAIN
    │
    ├── Websearch ────────────── WebSearch/  (+ TechNews tree today)
    ├── Prediction ───────────── Prediction/ + src/swarm_sdk/prediction/
    │       ├── BotDeal         product checkout
    │       └── feat/botdeal    sync target (sync_worktree.sh)
    ├── newsletter ───────────── Newsletter/
    ├── Agents ───────────────── Agents/ personas
    └── WebScraper ───────────── scraper (optional)
```

---

## 2. Main checkout tree (`Swarm/` on `swarm_sdk`)

```
Swarm/
├── src/swarm_sdk/            library + runtime
│   ├── agents/               manifests, packaged YAML (providers, registry, swarm)
│   ├── commands/             CLI verbs
│   ├── config/               Settings + providers.yaml loader
│   ├── core/                 swarm graph, allocator, jev router
│   ├── execution/            GIL / free-thread caps
│   ├── gpu/                  OpenCL / device
│   ├── math/
│   ├── memory/               mem0 + stores
│   ├── models/               chat, registry, breaker, selection
│   ├── observability/
│   ├── orchestrator/         plan / spawn / workers
│   ├── pb/                   protobuf
│   ├── prediction/           forecast façade (owned on Prediction lane)
│   ├── prompting/
│   ├── retrieval/            hybrid, gate, cache
│   ├── search/
│   ├── server/               HTTP / graphs
│   ├── serving/
│   ├── tuning/
│   ├── vault.py              Keychain / .env names only
│   └── cli.py
├── Agents/                   personas (edit on Agents lane)
├── WebSearch/                module (edit on Websearch)
├── Prediction/               module (edit on Prediction)
├── Newsletter/               digest (edit on newsletter)
├── TechNews/                 may be empty here if moved to TechNews branch
├── Main/                     host config / essentials
├── MCP/                      nested checkout / gitlink (do not treat as the SDK root)
├── tests/
├── docs/
├── scripts/
├── rust/
├── pyproject.toml
├── Tree.md                   this file
└── .env.example              env *names* only — values from 1Password / Keychain
```

---

## 3. Design workflow (ASCII)

Use this path for every change. Do not skip the lane check.

```
+=============================================================================+
|                     DESIGN WORKFLOW — MULTIPATH                             |
+=============================================================================+

                         +----------------------+
                         |  inbound request     |
                         |  (bug / feat / docs) |
                         +----------+-----------+
                                    |
                                    v
                         +----------------------+
                         | 0. TRIAGE            |
                         | which package?       |
                         | WebSearch / Predict  |
                         | Newsletter / Agents  |
                         | TechNews / SDK core  |
                         +----------+-----------+
                                    |
                                    v
              =================================================
              ||              OWNERSHIP GATE                 ||
              ||  Edit only in the worktree that owns it.    ||
              ||  Never copy folders across lanes.           ||
              =================================================
                     /            |            \
                    /             |             \
                   v              v              v
        +----------------+ +--------------+ +------------------+
        | PATH A         | | PATH B       | | PATH C           |
        | module         | | product      | | shared SDK       |
        | Websearch or   | | newsletter / | | swarm_sdk        |
        | Prediction     | | BotDeal /    | | src/swarm_sdk/** |
        |                | | TechNews     | | (not a product)  |
        +-------+--------+ +------+-------+ +--------+---------+
                |                 |                  |
                +--------+--------+------------------+
                         |
                         v
              +---------------------------+
              | 1. INSPECT                |
              | git -C <path> status      |
              | git -C <path> branch      |
              | read callers + tests      |
              +-------------+-------------+
                            |
                            v
              +---------------------------+
              | 2. DESIGN (this file)     |
              | ASCII: data flow + owner  |
              | smallest complete change  |
              +-------------+-------------+
                            |
                            v
              +---------------------------+
              | 3. IMPLEMENT              |
              | in the owner worktree     |
              | secrets: names only       |
              +-------------+-------------+
                            |
                            v
              +---------------------------+
              | 4. VERIFY                 |
              | cheapest failing check    |
              | then project gate         |
              +-------------+-------------+
                            |
              ============ VERIFY GATE ============
              | pass?  -->  5. REVIEW DIFF        |
              | fail?  -->  stop, do not weaken   |
              =====================================
                            |
                            v
              +---------------------------+
              | 5. HAND OFF               |
              | ask before commit/merge   |
              | source branch --> target  |
              | (usually swarm_sdk)       |
              +---------------------------+
```

### Merge policy

```
  feature/product lane ---- reviewed merge/cherry-pick ----> swarm_sdk (MAIN)
         ^
         |  module fix first, then product
         |
  Websearch / Prediction
```

Do not merge by copying trees. State source and target branches. Stop if the target is unclear.

---

## 4. Git commands (per lane)

```
git -C ~/Myworkspace/Swarm worktree list
git -C <worktree-path> status --short --branch
git -C <worktree-path> branch --show-current
```

GitKraken MCP: `git_worktree` on `~/Myworkspace/Swarm`; `git_status` on the lane path.

---

## 5. Credentials

Env var **names** live in `.env.example` and `src/swarm_sdk/agents/config/providers.yaml`.  
Values come from 1Password Environment **Swarm** (FIFO mounts) or Keychain (`uv run swarm-vault`). Never commit `.env`.
