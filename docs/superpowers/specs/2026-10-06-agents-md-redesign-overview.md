# SWARM-AGENTS-MD — Analyse codebase and create a better AGENTS.md

> **Epic planning overview** (repo-local; no Jira epic linked)  
> **Status:** draft — awaiting review before implementation plan  
> **Date:** 2026-10-06  
> **Branch context:** `feature/agents` (Agents + `src/` lane)

---

## 1. Epic overview

### Purpose

Contributors and Cursor coding assistants currently face **four overlapping instruction surfaces** (root `AGENTS.md`, `.cursor/AGENTS.md`, `.cursor/rules/*.mdc`, and 38+ persona `Agents/*/AGENTS.md` files) plus machine-wide `~/AGENTS.md`. The root file mixes onboarding map, quality gate, Python template encyclopedia, and swarm runtime detail. That increases token load, hides the “read this first” path, and duplicates content that already lives in rules, templates, and `Agents/_shared/COMMON.md`.

This epic defines a **layered documentation architecture** and delivers a **slimmer, decision-oriented root `AGENTS.md`** that points to single sources of truth without weakening gates or persona contracts.

### User value

- **Faster orientation:** assistants pick the right doc in one decision tree (repo work vs persona emulation vs Cursor ops).
- **Fewer contradictions:** one canonical place per concern (gate commands, template, security, worktrees).
- **Easier maintenance:** manifest validation and sync scripts stay green; new personas (PythonCoder, RustCoder, etc.) register consistently.

### Scope

**In scope**

- Root [`AGENTS.md`](../../../AGENTS.md) restructure (map + gates + links; no full template paste).
- Cross-links among [`README.md`](../../../README.md), [`Agents/SKILLS.md`](../../../Agents/SKILLS.md), [`Agents/README.md`](../../../Agents/README.md), [`.cursor/AGENTS.md`](../../../.cursor/AGENTS.md).
- Fix [`.gitignore`](../../../.gitignore) pattern that ignores all `AGENTS.md` files repo-wide.
- Optional validator enhancement: every `agent.yaml` has sibling `AGENTS.md`.
- Documentation-only unless a small validator test is needed.

**Out of scope**

- Rewriting all 38 persona contracts (use existing `sync_agents_template.py` workflow).
- Changing runtime swarm behavior in `src/swarm_sdk/`.
- Confluence/Jira automation (no credentials in repo).
- Merging `~/AGENTS.md` (machine-wide); only cross-reference in root doc.

### Key stakeholders

- **marilu** — primary contributor; Cursor-in-editor workflow.
- **Coding assistants** — root + `.cursor` consumers.
- **Swarm orchestration** — personas via `Agents/*/AGENTS.md` + `agent.yaml`.

---

## 2. Epic goals & success metrics

### Primary goal

A contributor or agent can answer “what do I read?” in **under 60 seconds** using root `AGENTS.md` alone, then drill into specialists only when needed.

### Success metrics

| Metric | Target |
|--------|--------|
| Root `AGENTS.md` line count | ≤ 180 lines (from ~234); template detail only linked |
| Duplicate gate command blocks | 1 canonical block (root); `.cursor` + rules link to it |
| `swarm_sdk.agents.validate` | Green; optional new check for `AGENTS.md` presence |
| Persona index consistency | `SKILLS.md`, `README.md`, `coordination.yaml` agree on active roster |
| Assistant routing errors (informal) | No conflicting “which AGENTS wins” in root vs `.cursor` preamble |

### KPIs

- Time-to-first-correct gate command (self-reported / spot checks).
- Zero new secrets in YAML/docs after edits (`test_yaml_never_holds_secret_values` stays green).

---

## 3. Requirements summary

### Functional requirements

1. Root `AGENTS.md` must include: project one-liner, two agent kinds (coding assistant vs swarm persona), **decision tree**, repo map (table), quality gate (copy-paste commands), security summary, git/worktree pointer, links to SKILLS/coordination/templates.
2. `.cursor/AGENTS.md` remains the **Cursor operating manual** (modus operandi, folder design, STOP table); must not duplicate full gate block—link to root.
3. Persona contracts stay in `Agents/<Name>/AGENTS.md`; shared boilerplate stays in `Agents/_shared/COMMON.md` + `TEMPLATE.md`.
4. `.gitignore` must not ignore tracked repo `AGENTS.md` files (fix `AGENTS.md` glob).

### Non-functional requirements

- Markdown lint friendly (100-col wrap where already configured).
- Links use repo-relative paths valid on GitHub.
- No API keys or env values in docs.

### Business rules

- Root wins for product/runtime; `.cursor/AGENTS.md` wins for Cursor ops (existing rule—state explicitly once).
- Do not paste full `python_static_template.py` into `AGENTS.md` (CI/template rule preserved).

### Edge cases

- Worktrees (`WebSearch`, `../Swarm-Prediction`, `../Newsletter`) — root map must keep sibling paths.
- `AGENTS.md` gitignored at repo root but tracked: fix ignore rules (`/AGENTS.md` local only vs `!/AGENTS.md` exceptions).
- Personas without `langgraph_node` still need contracts for plan orchestrator path.

---

## 4. Technical change overview

| Component | Type | Description | Risk | Dependencies |
|-----------|------|-------------|------|--------------|
| `AGENTS.md` (root) | Refactor | Slim map + decision tree; move template tables to links | Low | None |
| `.cursor/AGENTS.md` | Enhancement | Dedupe gate; link root § Quality gate | Low | Root edit |
| `.cursor/rules/core.mdc` | Enhancement | Ensure pointers match new root headings | Low | Root edit |
| `.gitignore` | Fix | Stop ignoring all `AGENTS.md` | Med | Legal review of intent |
| `Agents/README.md` | Enhancement | Align roster with SKILLS (Researcher, Benchmarker, new coders) | Low | coordination |
| `Agents/SKILLS.md` | Enhancement | Register new personas; remove stale entries | Low | manifests |
| `src/swarm_sdk/agents/validate.py` | Enhancement | Optional: fail if `AGENTS.md` missing next to manifest | Med | Tests in benchmark |
| `docs/superpowers/plans/*` | New | Implementation plan ticket breakdown | Low | This overview approved |

**Risk scores (7-dimension sum):** predominantly **Low (7–11)**; `.gitignore` + validator **Medium (12–14)**.

---

## 5. Impact analysis

### Codebase impact

- **Docs:** `AGENTS.md`, `.cursor/AGENTS.md`, `README.md`, `Agents/README.md`, `Agents/SKILLS.md`, possibly `Documents/SWARM-DOC-MAP.md`.
- **Tooling:** `.gitignore`, optional `validate.py` + one test file under `Agents/benchmark/tests/`.
- **No** runtime API changes.

### Data model changes

None.

### API changes

None.

### UI/UX changes

Improved assistant behavior (correct doc routing) in Cursor/VS Code.

### Migration strategy

1. Land doc architecture on `feature/agents` or `docs/agents-md` branch.
2. Update cross-links in same PR.
3. Fix `.gitignore` in same PR so new persona `AGENTS.md` files can be committed intentionally.

### Rollback plan

Revert doc commit(s); validator check is additive and can be reverted independently.

### Tradeoffs

- **Shorter root doc** vs **offline completeness** — mitigated by stable links to templates and `_shared/COMMON.md`.
- **Stricter validator** may fail until orphan folders get manifests or are removed from tree.

---

## 6. Testing strategy

### Unit testing

- If validator extended: `Agents/benchmark/tests/test_agent_validate.py` (or existing validate tests) — manifest without `AGENTS.md` fails.

### Integration testing

- `uv run python -m swarm_sdk.agents.validate` after coordination/README edits.

### API testing

N/A.

### Test data

Use temporary fixture agent dir in tests (existing patterns in benchmark tests).

### Coverage goals

Validator new branch: 100% of new lines; no requirement for 90% repo-wide on docs-only epic.

---

## 7. User behavior testing

### E2E scenarios

1. New contributor opens repo → reads root `AGENTS.md` → runs quality gate successfully.
2. Cursor agent tasked with “fix Python in src” → reads root only → does not load Planner persona contract.
3. Cursor agent emulating Coder → opens `Agents/Coder/AGENTS.md` + `agent.yaml`.
4. Add `Agents/Foo/agent.yaml` without `AGENTS.md` → validate fails (if ticket 106 landed).

### Acceptance test cases

- All links in root `AGENTS.md` resolve (manual or `markdown-link-check` if available).
- `ruff`/`ty` unchanged by doc-only PR.

### Regression testing

- `test_yaml_never_holds_secret_values`
- Full quality gate on any validator code change

---

## 8. Implementation notes

### Patterns to follow

- Superpowers spec tone: [`2026-10-05-benchmark-protocol-design.md`](2026-10-05-benchmark-protocol-design.md) — goal, decision, scope, tests.
- Persona shape: [`Agents/TEMPLATE.md`](../../../Agents/TEMPLATE.md), sync via `Agents/_shared/sync_agents_template.py`.
- Cursor ops: [`.cursor/AGENTS.md`](../../../.cursor/AGENTS.md) modus operandi loop.

### Architecture decisions

| Decision | Rationale |
|----------|-----------|
| **Three layers** — Map (root) / Ops (`.cursor`) / Role (`Agents/*`) | Matches two kinds of agents + editor tooling |
| **Decision tree at top of root** | Reduces wrong-file reads |
| **Single gate block** | Prevents drift between root and rules |
| **Fix `.gitignore`** | `AGENTS.md` entry currently blocks committing persona docs |

### Proposed root decision tree (to embed)

```text
                    [ Task received ]
                           |
            +--------------+--------------+
            |                             |
    Emulating Agents/<Role>?        General repo / SDK work?
            |                             |
            v                             v
    Agents/<Role>/AGENTS.md         Root AGENTS.md
    + agent.yaml                    + quality gate
            |                             |
            |                    Cursor-specific ops?
            |                             |
            |                             v
            |                    .cursor/AGENTS.md
            |                    + .cursor/rules/
            v                             v
    coordination.yaml              src/ + Agents/benchmark tests
    if multi-step swarm
```

### Technical debt

- `Agents/TEMPLATE.md` is very long (includes full AgentMethods); root should link, not duplicate.
- `antigravity-imported/` reference-only copies inflate search hits — document as non-runtime.
- Machine-wide `~/AGENTS.md` duplicates some gate text — root should say “project overrides home defaults”.

### Security considerations

- No change to secret handling; reinforce link to `Agents/Security/AGENTS.md` and security rule.

---

## 9. Acceptance criteria

- [ ] Root `AGENTS.md` ≤ 180 lines with decision tree and no full template paste
- [ ] `.cursor/AGENTS.md` references root for quality gate (no duplicate 4-line command block)
- [ ] `.gitignore` fixed so project `AGENTS.md` files are committable
- [ ] `Agents/README.md` and `SKILLS.md` roster matches `coordination.yaml` + manifests (39 OK today)
- [ ] `uv run python -m swarm_sdk.agents.validate` passes
- [ ] `Documents/SWARM-DOC-MAP.md` updated if doc paths change
- [ ] Implementation plan published under `docs/superpowers/plans/`

---

## 10. Open questions & risks

### Blockers

- None for doc work; Jira/Confluence not configured for this repo.

### Unknowns

- Should **new coder personas** (PythonCoder, RustCoder, JSCoder, Infra, …) be added to `coordination.yaml` in this epic or a follow-up?
- Should root `AGENTS.md` mention **`frontend/`** and **`codeworkspace/`** explicitly (currently absent)?

### Assumptions

- Tracked root `AGENTS.md` remains the canonical GitHub-visible contributor entry (not gitignored).
- User wants **English** docs only for this pass.

### Risks

| Risk | Mitigation |
|------|------------|
| `.gitignore` fix accidentally commits unwanted local AGENTS | Use `/AGENTS.md` only at repo root for “local override” or document `!Agents/**/AGENTS.md` |
| Slimming root too far | Keep full gate commands once in root |
| Validator break on BenchmarkCreator folder | Remove stale dir or add manifest |

---

## 11. Codebase analysis

### Affected modules

| Path | Role in epic |
|------|----------------|
| `AGENTS.md` | Primary deliverable |
| `.cursor/AGENTS.md` | Cursor ops; dedupe |
| `.cursor/rules/*.mdc` | alwaysApply pointers |
| `Agents/_shared/COMMON.md` | Shared validation/gate text |
| `Agents/TEMPLATE.md` | Persona authoring |
| `Agents/SKILLS.md` | Specialist catalog |
| `Agents/README.md` | Human index table |
| `Agents/coordination.yaml` | Registry truth |
| `src/swarm_sdk/agents/validate.py` | Optional AGENTS.md check |
| `.gitignore` | Fix AGENTS.md ignore |
| `README.md` | Contributor entry link |
| `Documents/SWARM-DOC-MAP.md` | Doc bridge |

**Scale:** ~100 `AGENTS.md` paths on disk (includes `node_modules`/vendor copies under some trees); **39** `agent.yaml` manifests; **32** coordination agents; validate reports **39 manifests OK**.

### Patterns discovered

**Documentation layering**

- Root: map + gates + security + git (narrative topics with anchors).
- `.cursor`: Think→Check→Plan loop, STOP table, folder ASCII map.
- `Agents/*`: Persona, scope, workflow ASCII, output JSON contract, link to TEMPLATE.
- Rules: always-on slices (`core.mdc`, `security.mdc`, `git-docs.mdc`).

**Validation**

- `uv run python -m swarm_sdk.agents.validate` — coordination ↔ manifest cross-check.
- Quality gate: pytest under `Agents/benchmark`, ruff/ty on `src`, `Agents/benchmark`, `Main`.

**Persona registration**

- `agent.yaml` + `AGENTS.md` per folder; `langgraph_node` optional for plan workers.
- Sync tooling: `Agents/_shared/sync_agents_template.py`.

### Reference implementations

| Reference | Reuse |
|-----------|--------|
| [`docs/superpowers/specs/2026-10-05-benchmark-protocol-design.md`](2026-10-05-benchmark-protocol-design.md) | Spec structure |
| [`docs/superpowers/plans/2026-10-02-langgraph-swarm-hardening.md`](../plans/2026-10-02-langgraph-swarm-hardening.md) | Scoped implementation plan + gate |
| [`Agents/PythonCoder/AGENTS.md`](../../../Agents/PythonCoder/AGENTS.md) | Lean persona with workflow ASCII |
| [`Agents/_shared/COMMON.md`](../../../Agents/_shared/COMMON.md) | Shared gate table for personas |

### Test locations & conventions

| Kind | Location | Pattern |
|------|----------|---------|
| Agent validate | CLI `python -m swarm_sdk.agents.validate` | Exit 0 / stderr errors |
| Benchmark tests | `Agents/benchmark/tests/` | `test_*.py` |
| YAML secrets | benchmark tests | `test_yaml_never_holds_secret_values` |
| Persona benchmarks | `Agents/*/Benchmarks/README.md` | Notes only |

---

## 12. Linked tickets (proposed)

**Epic:** SWARM-AGENTS-MD — Analyse codebase and create a better AGENTS.md  
**Jira project:** N/A (repo-local)

| Key | Summary | Type | Points |
|-----|---------|------|--------|
| SWARM-AGENTS-101 | Doc architecture: decision tree + layer table in root `AGENTS.md` | Story | 3 |
| SWARM-AGENTS-102 | Slim root: move template role table to template link only | Task | 2 |
| SWARM-AGENTS-103 | Dedupe `.cursor/AGENTS.md` vs root (gate, map) | Task | 2 |
| SWARM-AGENTS-104 | Fix `.gitignore` for `AGENTS.md` / `SKILL.md` patterns | Bug | 2 |
| SWARM-AGENTS-105 | Sync `Agents/README.md` + `SKILLS.md` roster | Task | 3 |
| SWARM-AGENTS-106 | Validator: require `AGENTS.md` beside each manifest | Story | 3 |
| SWARM-AGENTS-107 | Update `SWARM-DOC-MAP.md` + README contributor section | Task | 1 |
| SWARM-AGENTS-108 | Register new coder/infra personas in coordination (optional) | Story | 5 |

**Suggested implementation order:** 104 → 101 → 102 → 103 → 105 → 107 → 106 → 108

---

## Risk profile summary

| Level | Count | Items |
|-------|-------|--------|
| Low | 6 | 101, 102, 103, 105, 107, most of 101 |
| Medium | 2 | 104, 106 |
| High | 0 | — |

---

## Document control

| Field | Value |
|-------|--------|
| Overview document (repo) | `docs/superpowers/specs/2026-10-06-agents-md-redesign-overview.md` |
| Confluence | Not published (no project URL) |
| Next command | `/create-implementation-plan docs/superpowers/specs/2026-10-06-agents-md-redesign-overview.md` |
