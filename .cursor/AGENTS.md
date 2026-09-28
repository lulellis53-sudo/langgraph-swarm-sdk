# Cursor agent guidelines — Swarm

Scoped instructions for Agent work under `.cursor/`. Complements the root [`AGENTS.md`](../AGENTS.md); when they conflict, **root + specialist `Agents/*/AGENTS.md` win for product/runtime**, and this file wins for **how the Cursor agent operates**.

## Guidelines

1. **Read first** — callers, tests, and config that touch the same behavior before editing.
2. **Smallest correct diff** — no drive-by refactors, new abstractions, or dependencies unless required.
3. **Match the stack** — Python `>=3.14.5`, `uv run …`, Ruff + ty (see root quality gate).
4. **Prove it** — failing test → fix → gate (`pytest`, `ruff`, `ty`, `swarm_sdk.agents.validate`).
5. **No secrets** — never commit or paste `.env`, keys, or tokens.
6. **Docs after editing** — after substantive library/API edits, use **Context7** (preferred), then **Tavily** or **Exa**; tighten from current docs before claiming done.
7. **Delegated work** — use Cursor subagents (`.cursor/agents/` when present) or Swarm personas (`Agents/*`) with clear prompts; parallelize independent multitasks.

## Folder design

```text
.cursor/
├── AGENTS.md           # This file — Cursor agent modus operandi
├── commands/           # Slash commands (e.g. sql-pro.md)
├── extensions.txt      # Recommended extensions install list
├── agents/             # Optional custom subagents (*.md)
├── skills/             # Optional project skills (*/SKILL.md)
└── rules/              # Project rules (*.mdc) — always-on + globs
    ├── core.mdc
    ├── context7-after-edit.mdc
    ├── security.mdc
    ├── python.mdc
    ├── protobuf.mdc
    ├── config-yaml.mdc
    ├── swarm-agents.mdc
    ├── tests-benchmark.mdc
    └── git-docs.mdc
```

Repo (outside .cursor/) that agents must respect:
```text
├── AGENTS.md           # Project-wide coding / Swarm map
├── Agents/             # Swarm personas + per-role Benchmarks/
├── src/swarm_sdk/      # Library (pb/, orchestrator/, …)
├── config/             # swarm.yaml, model registry
├── tests/              # Unit / integration
└── benchmark/          # Shared harnesses (sql_pro, Tasks/, …)
```

| Path | Put here |
|------|----------|
| `.cursor/commands/` | Reusable `/` workflows |
| `.cursor/agents/` | Isolated specialist subagents |
| `.cursor/skills/` | On-demand skill packs |
| `.cursor/rules/` | Scoped `.mdc` rules (not plain `.md`) |
| `Agents/*/Benchmarks/` | Role-scoped notes only; runners stay in `benchmark/` |

## Modus operandi

Operate in this loop. Do **not** skip **Check**. Do **not** skip **Context7 after editing** on library/API work.

```text
Think → Check → Plan (multitasks) → Act → Context7 (after edit) → Tighten → re-Check
```

### 1. Think

- Restate the goal and success criteria in one or two sentences.
- Identify constraints (scope, files off-limits, secrets, quality gate).
- Prefer the existing pattern in-repo over inventing a new one.

### 2. Check

- Locate callers, tests, and configs with search/read tools.
- Note open questions or risks before writing code.
- If the environment is blocked, report `blocked` with the exact command/error after one retry.

### 3. Plan (multitasks)

- Split into independent vs dependent steps.
- Run independent work in parallel (tool batches / subagents).
- Keep dependent steps sequential; name what each step must return.

### 4. Act

- Edit, run the relevant tests/gate for the change, and leave the tree reviewable.
- Update docs/commands only when behavior or install steps change.

### 5. Context7 (after editing)

- After the edit lands, query **Context7 MCP** for current docs (resolve library id → query-docs).
- Fall back to **Tavily** or **Exa** when Context7 has no coverage or you need live web confirmation.
- Apply only what improves correctness, security, or maintainability — do not bloat the diff.

### 6. Think / Tighten

- Integrate doc findings; drop obsolete assumptions.
- Confirm the smallest change still satisfies the goal; re-run checks if you changed code again.
- Summarize outcomes briefly for the user (what changed, how to verify).

## Quick references

- Root agent map: [`../AGENTS.md`](../AGENTS.md)
- Swarm roles: [`../Agents/SKILLS.md`](../Agents/SKILLS.md)
- Extensions: [`extensions.txt`](extensions.txt)
- Example command: [`commands/sql-pro.md`](commands/sql-pro.md)
