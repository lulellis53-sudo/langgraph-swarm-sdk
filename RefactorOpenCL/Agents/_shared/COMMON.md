# Shared swarm specialist defaults

Persona authoring: [`../TEMPLATE.md`](../TEMPLATE.md). Method depth:
[`../AgentMethods.md`](../AgentMethods.md). Each `Agents/<Name>/AGENTS.md` maps
TEMPLATE sections to local headings; this file holds **lean** shared text so it
is not duplicated in every contract.

## Python modules

When a persona creates or substantially edits Python under the repo:

1. Module docstring, then `from __future__ import annotations`.
2. Prefer the **lite** scaffold for small modules; use the **full** scaffold when
   the module needs batch, DB, or vector roles.
3. Use `@wrappers.retry_transient` only for transient I/O errors; `@wrappers.timed`
   only when profiling is enabled.
4. Public payloads: Pydantic v2 (`BaseModel`, `Field`, `ConfigDict`,
   `model_validate` / `model_dump`), not untyped `dict` or v1 `class Config`.
5. Copy and trim scaffolds from the repo’s canonical Python static template
   (see root `AGENTS.md`); **do not** import template files from runtime code.

## Operating principles

1. **Understand before changing** — read implementation, callers, tests, and config.
2. **Stay in scope** — smallest complete change; no unrelated edits.
3. **Preserve contracts** — public APIs, schemas, and behavior unless the task requires change.
4. **Use evidence** — no invented commands, test results, or URLs.
5. **Fail explicitly** — no broad swallow, silent fallback, or fake success JSON.
6. **Protect secrets** — never log or commit credentials; env var **names** only in YAML.
7. **Report honestly** — distinguish unrun checks from passing checks; `blocked` is valid.

## Tools and permissions

Defaults for **LangGraph Swarm SDK** repo work:

| Capability | Allowed | Restrictions |
| --- | --- | --- |
| Read / search | Repo tree, docs, approved web/MCP | No exfiltration; respect `.gitignore` |
| Edit / write | Paths in plan `files` or role scope | Read-only personas never patch production code |
| Shell | `uv run …`, project scripts | No destructive git; no global installs without ask |
| Delegation | Other manifests via Orchestrator/Planner | Disjoint `files` per parallel Coder step |

Each agent’s **`agent.yaml` → `capabilities`** narrows this list. If a capability is not
listed, do not assume it.

## Validation

When the task changes **`src/`**, **`Agents/benchmark/`**, or **`Main/`**:

| Check | Command | When |
| --- | --- | --- |
| Tests | `uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 pytest Agents/benchmark -q` | After behavior change |
| Lint | `uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 ruff check src Agents/benchmark Main` | Before handoff |
| Types | `uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 ty check src Agents/benchmark Main` | Before handoff |
| Manifests | `uv run python -m swarm_sdk.agents.validate` | After `agent.yaml` / coordination edits |

**WebSearch pipeline** (WebFetch / Normalizer / Persister): run tests under `WebSearch/`
or `Agents/benchmark` tasks named for websearch when those paths change.

Rules:

- Run the **narrowest** check first; widen if shared code or failures warrant it.
- Put commands actually run into `test_commands` or output `checks`.
- One focused fix per failed check, then rerun **that** check (see error recovery below).

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
        Continue / handoff    Classify cause → one focused fix
                              → rerun SAME check (max 1 retry
                              unless task allows more)
                              → else blocked + evidence
```

Do not retry infrastructure, permissions, or ambiguous requirements without new input.
Review/research **findings** are outcomes, not checks to retry away.

## Completion checklist

- [ ] Acceptance criteria met or `blocked` / `needs_input` with evidence
- [ ] Unrelated user or pre-existing changes preserved
- [ ] Tests/docs updated when behavior or public surface changed
- [ ] Validation run and recorded accurately (or skipped with reason)
- [ ] No secrets, drive-by refactors, or scratch artifacts left behind
- [ ] Output contract / handoff JSON matches human summary
