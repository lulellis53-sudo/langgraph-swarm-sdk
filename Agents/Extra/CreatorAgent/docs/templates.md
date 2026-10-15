# Autonomous Agent Templates Reference (`templates.md`)

> **Authoritative Specification**: Reusable Persona & Manifest Templates for `CreatorAgent`.
> **Source Foundation**: Consolidated from `TEMPLATE.md`, `TEMPLATE1.md`, and `TEMPLATE3.md`.

---

## 1. Canonical `AGENTS.md` Skeleton

```markdown
# Agent: [AgentName]

> **Precedence**: Safety, user instructions, project files, these defaults.
> **Shared Defaults**: [`../_shared/COMMON.md`](../_shared/COMMON.md)

---

## 1. Scope, Role & Primary Directives

- **Agent Name**: `[AgentName]`
- **Role**: [One sentence describing single primary function]
- **Prime Directive**: [Core objective, e.g., 100% test passing, zero grade inflation, deterministic formatting]
- **Read/Write Boundaries**: [Explicit read and write path restrictions]

---

## 2. ASCII Multipath Decision Flow

\`\`\`text
[Inbound Request]
        │
        v
[Phase 1: Intake & Triage]
        │
        ├─ Simple / 1-Step ──► Fast-Path Direct Execution
        └─ Complex / Risky  ──► In-Memory Plan + Verification Criteria
                                │
                                v
                    [Phase 2: Bounded Execution]
                                │
                                v
                    [Phase 3: Empirical Verification Gate]
                                │
                                v
                    [Emit JSON Output Contract]
\`\`\`

---

## 3. Tasks & Operational Specifications

| `task` | Trigger / Condition | Primary Execution Pattern | Outputs & Artifacts |
| :--- | :--- | :--- | :--- |
| `[task_id_1]` | [Trigger condition] | [Method pattern] | `[output_1]`, `[output_2]` |
| `[task_id_2]` | [Trigger condition] | [Method pattern] | `[output_1]` |

---

## 4. Behavioral Guidelines & Checklists

### Pre-Task Checklist
- [ ] Task scope clearly defined.
- [ ] Input parameters validated against schema.
- [ ] Working directory set inside workspace root.

### Post-Task Checklist
- [ ] Zero unverified claims or untested code.
- [ ] Linter and static typing checks exit 0.
- [ ] Output contract populated.
```

---

## 2. Canonical `agent.yaml` Manifest Skeleton

```yaml
version: '1'
name: [AgentName]
role: [canonical_role_identifier]
model: [provider:model_name] # e.g. anthropic:claude-sonnet-4.6 or openrouter:z-ai/glm-5.3-flash
think_level: high # low | medium | high | xhigh
effort: high     # low | medium | high
api_key_env: [VAULT_ENV_KEY] # e.g. CLAUDE_OAUTH_TOKEN or OPENROUTER_API_KEY
token_budget:
  max_prompt: 8192
  max_completion: 4096
capabilities:
- [capability_1]
- [capability_2]
tasks:
- id: [task_id_1]
  description: '[Clear description of task]'
  outputs:
  - [output_1]
telemetry:
  enabled: true
  metrics:
  - token_count
  - latency_ms
  - throughput_rpm
  - jev_score
  - success_rate
  export_format: json_lines
  log_destination: Benchmark/telemetry.jsonl
skills:
- skills/SKILL.md
- TOOLS.md
```

---

## 3. Canonical `skills/SKILL.md` Skeleton

```markdown
---
name: [AgentName]Skill
description: "[One-sentence description of the specialized capability.]"
---

# [AgentName] Skill Specification

## 1. Overview & Objective
[Detailed operational capabilities and domain procedures.]

## 2. Tooling Usage Rules
1. Call native tools over shell where possible.
2. Bound all output streams (`rg -m 50`, `head -n 100`).
```

---

## 4. Canonical `memory/MEMORY.md` Skeleton

```markdown
# Agent Memory: [AgentName]

> **Agent Memory Ledger**: Local episodic, semantic, and task checkpoint memory store.

---

## 1. Memory Store Architecture
- **Episodic Memory**: Task execution outcomes and run ledgers.
- **Semantic Cache**: Domain invariants and verified entity relationships.
- **Checkpoint Ledger**: Rollback snapshots before major code mutations.
```

---

## 5. Canonical `TOOLS.md` Skeleton

```markdown
# Agent Tools Specification: [AgentName]

> **Authoritative Specification**: Tooling, external API integrations, and validation engines for `[AgentName]`.

---

## 1. Core Tooling Catalog
- **Engine 1**: Purpose and execution instructions.
- **Engine 2**: Purpose and execution instructions.
```
