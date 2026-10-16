# Shared swarm specialist defaults

Persona authoring: [`../TEMPLATE.md`](../TEMPLATE.md) when present. Method depth:
[`../AgentMethods.md`](../AgentMethods.md). **Jev routing diagram (all agents):**
[`JEV_MULTIROUTER.md`](JEV_MULTIROUTER.md).

## Python modules

When a persona creates or substantially edits Python under the repo:

1. Line 1: `from __future__ import annotations` (module docstring after it).
2. Public payloads: Pydantic v2; see root `AGENTS.md` and `.cursor/templates/`.

## Operating principles

1. **Understand before changing** — read implementation, callers, tests, and config.
2. **Stay in scope** — smallest complete change; no unrelated edits.
3. **Preserve contracts** — public APIs, schemas, and behavior unless the task requires change.
4. **Use evidence** — no invented commands, test results, or URLs.
5. **Fail explicitly** — no broad swallow, silent fallback, or fake success JSON.
6. **Protect secrets** — never log or commit credentials; env var **names** only in YAML.
7. **Report honestly** — distinguish unrun checks from passing checks; `blocked` is valid.

## Tools and permissions

| Capability | Allowed | Restrictions |
| --- | --- | --- |
| Read / search | Repo tree, docs, approved web/MCP | No exfiltration; respect `.gitignore` |
| Edit / write | Paths in plan `files` or role scope | Read-only personas never patch production code |
| Shell | `pixi run …`, project scripts | No destructive git; no global installs without ask |
| Delegation | Other manifests via Orchestrator/Planner | Disjoint `files` per parallel Coder step |

Each agent’s **`agent.yaml` → `capabilities`** narrows this list.

## Validation

| Check | Command | When |
| --- | --- | --- |
| Tests | `pixi run python -m pytest Core Agents -q --tb=short` | After behavior change |
| Lint | `pixi run check` | Before handoff |
| Jev routing | `pixi run python -m Core.benchmark.run --task jev_agent_routing` | After `jev_router` / routing cases change |

Run the narrowest check first; record commands in `test_commands` or output `checks`.

## Error recovery

```text
              +-------------------------+
              | Run the relevant check  |
              +------------+------------+
                           |
                 +---------+---------+
                 |                   |
               PASS                 FAIL
                 |                   |
                 v                   v
        Continue / handoff    One focused fix → rerun SAME check
                              → else blocked + evidence
```

## Completion checklist

- [ ] Acceptance criteria met or `blocked` / `needs_input` with evidence
- [ ] Unrelated changes preserved
- [ ] Validation run and recorded (or skipped with reason)
- [ ] No secrets or scratch artifacts left behind
- [ ] Output contract matches human summary
