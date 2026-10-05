# SWARM-JEV — Parallel workflow swarm with JEV multi-decision routing

**Epic key (proposed):** `SWARM-JEV`  
**Status:** Draft overview — Jira epic not linked (provide `{PROJECT}-{number}` to sync tickets)  
**Repo:** LangGraph Swarm SDK (`/Users/usuario/Swarm`)

---

## 1. Epic overview

### Purpose

Turn the **23 specialist personas** in `Agents/*/AGENTS.md` into a **real parallel
workflow swarm**: dependency-wave execution (`run_plan`), disjoint file ownership,
and **Jev System-1** routing (`NoulDecision`, `ScoreDecision`, `ChoiceDecision`)
at intake and per-step boundaries — not a single Coder loop.

### User value

- Faster goals via **parallel waves** (independent steps concurrent up to `max_concurrency`).
- Cheaper runs via Jev **complexity tiering** (`flash_lite` / `flash` / `pro`).
- Safer automation via Jev **safety gate** before write paths execute.
- Correct specialist selection via **ChoiceDecision** over manifest names aligned with decision trees in each `AGENTS.md`.

### Scope

**In scope**

- Wire `JevRouter` into **plan orchestrator** (`spawn` → `run_plan`) and optionally handoff graph entry.
- Multi-decision path: safety → score/tier → discrete agent choice where Planner/Orchestrator leaves ambiguity.
- `coordination.yaml` + benchmark tasks proving parallel Coder waves and pipeline coworkers.
- Persona contracts (Persona-first `AGENTS.md`, JSON handoffs, DARS/ReAct via `AgentMethods.md`).

**Out of scope**

- Replacing LangGraph handoff mesh (`researcher` / `coder` / `reviewer`) entirely.
- Confluence/Jira automation (until epic key and credentials confirmed).
- New Antigravity mirror catalogs.

### Key stakeholders

- Swarm SDK maintainers, benchmark/CI, host rules (16 GB / Lifeguard / JEV latency budgets).

---

## 2. Epic goals and success metrics

| Goal | Metric |
| --- | --- |
| Parallel plan execution | ≥2 steps in one wave on a reference plan; wall time ↓ vs sequential baseline |
| Jev routing live on plan path | 100% of plan steps record `jev_decision` in structured output when enabled |
| Choice routing accuracy | Benchmark suite: `evaluate_choice` matches expected agent on fixed prompts (existing tests green + new plan-routing cases) |
| Safety gate | Unsafe prompts blocked before Coder write (`NoulDecision.decision == false`) |
| Token/cost | `ScoreDecision` maps trivial tasks to `flash_lite` on reference set |

---

## 3. Requirements summary

### Functional

1. **Spawn:** Orchestrator produces valid `Plan` with waves; Coder steps declare disjoint `files`.
2. **Run:** `run_plan` executes each wave with `bounded_gather` and `parallelism.max_concurrency`.
3. **Jev intake:** Before each worker step (or wave), run `evaluate_noul` on step title+description+files context; abort step on unsafe.
4. **Jev tier:** Run `evaluate_score`; pass `model_tier` into worker model selection (ModelDelegate or manifest override policy TBD).
5. **Jev choice:** When step `agent` is empty or `ModelDelegate` routes sub-task, `evaluate_choice` over allowed manifest names from plan context.
6. **Handoff:** Each step emits JSON contract from persona `AGENTS.md`; plan result aggregates outputs.

### Non-functional

- Local Jev fallback **&lt;10 ms** per decision (existing test contract).
- Remote Jev optional via `JEV_ENDPOINT` / `JEV_API_KEY` (vault).
- No secrets in logs; YAML holds env names only.

### Edge cases

- Circular `depends_on` → plan validation fails at spawn.
- Overlapping Coder `files` in same wave → spawn validation rejects.
- Jev remote timeout → local fallback (existing `jev_router` behavior).

---

## 4. Technical change overview

| Component | Type | Description | Risk | Dependencies |
| --- | --- | --- | --- | --- |
| `src/swarm_sdk/orchestrator/worker.py` | Enhancement | Inject JevRouter per step; attach decision to `StepOutput` | Med | `jev_router`, model select |
| `src/swarm_sdk/orchestrator/graph.py` | Enhancement | Optional pre-wave Jev batch; concurrency unchanged | Low | worker |
| `src/swarm_sdk/orchestrator/spawn.py` | Enhancement | Planner prompt lists agents + task ids; validate choice candidates | Med | manifests |
| `src/swarm_sdk/orchestrator/plan.py` | Enhancement | Optional `jev_metadata` on steps | Low | pydantic |
| `src/swarm_sdk/core/jev_router.py` | Fix/Enhancement | Align `_CANDIDATE_KEYWORDS` with all 23 manifest names | Med | Agents renames |
| `src/swarm_sdk/server/graphs.py` | Enhancement | `plan` graph: Jev-enabled factory | Med | worker |
| `Agents/coordination.yaml` | Enhancement | Reference tasks for parallel + websearch pipeline | Low | validate |
| `Agents/benchmark/tests/` | New | Integration: plan + Jev + parallel wave | Med | fixtures |
| `Documents/LangSwarm.md` | Docs | §9 Jev integration status updated | Low | code |
| `Main/config/swarm.yaml` | Config | Feature flag `jev_routing_enabled` (proposed) | Low | — |

**Risk profile (draft):** 4 low, 5 medium, 0 high (no schema migrations).

---

## 5. Impact analysis

- **Codebase:** `src/swarm_sdk/orchestrator/*`, `core/jev_router.py`, `low_swarm.py` (reference pattern), `server/graphs.py`, `Agents/*`.
- **Data model:** None (optional JSON fields on step outputs).
- **API:** gRPC/API plan runs expose Jev metadata in responses when enabled.
- **Rollback:** Feature flag off → current worker path without Jev.
- **Tradeoff:** Jev choice adds latency per step vs LLM-only Orchestrator assignment; mitigated by local fallback and caching scores within a wave.

---

## 6. Testing strategy

| Layer | Target |
| --- | --- |
| Unit | Existing `tests/test_jev_router.py` (keep green) |
| Unit | Plan validation: overlapping files, unknown agents |
| Integration | `spawn` + `run_plan` mock workers: 2-step parallel wave completes |
| Integration | Unsafe step blocked by Noul |
| Benchmark | `Agents/benchmark` quality gate unchanged + new test module |

Coverage: follow repo gate (`pytest Agents/benchmark -q`); aim for branch coverage on new orchestrator branches (project default; adjust if epic ticket specifies 90%).

---

## 7. User behavior testing

Scenarios (acceptance):

1. Goal → Orchestrator → plan with Researcher ∥ Documenter (read-only) then Coder.
2. Two Coder steps, disjoint `files`, same wave — both complete, no path collision.
3. WebSearch pipeline: WebFetch → Normalizer → Persister (deterministic, no LLM).
4. Destructive shell in step description → Jev blocks before worker runs.

---

## 8. Implementation notes

### Patterns to follow

- **Parallel waves:** `src/swarm_sdk/orchestrator/graph.py` — wave barriers + `bounded_gather`.
- **Jev node pattern:** `src/swarm_sdk/orchestrator/low_swarm.py` — `node_jev_router`, conditional edges.
- **Persona contracts:** `Agents/*/AGENTS.md` — Persona → decision tree → JSON output; methods in `AgentMethods.md` / `_shared/ACTUATION.md`.
- **Manifest source of truth:** `Agents/*/agent.yaml` via `load_all_agent_manifests`.

### Architecture decision

Use **Jev at worker boundary** (each `PlanStep` execution), not inside every LLM token stream — matches System-1 latency budget and keeps ReAct inside the specialist LLM.

### Security

- Noul patterns in `jev_router.py`; never bypass for Coder write steps.
- Reviewer/Security remain read-only audit path after Coder waves.

---

## 9. Acceptance criteria (epic done)

- [ ] Feature-flagged Jev routing on `run_plan` with structured `jev_decision` on outputs
- [ ] `evaluate_choice` candidate set = manifest names assigned by plan (or full catalog policy documented)
- [ ] Reference parallel plan in benchmark or docs executes 2+ steps in one wave
- [ ] `uv run python -m swarm_sdk.agents.validate` green
- [ ] Quality gate green (pytest, ruff, ty on touched paths)
- [ ] `Documents/LangSwarm.md` §9 reflects implemented wiring

---

## 10. Open questions and risks

| Item | Type |
| --- | --- |
| Jira epic key and linked tickets | Blocker for `/create-implementation-plan` Confluence chain |
| Per-step vs per-wave Jev | Technical decision |
| Override manifest `model` with `ScoreDecision.model_tier` | Policy |
| Handoff graph (`create_swarm`) also uses Choice for transfers? | Scope |
| Remote Jev SLA in CI | Environment |

**Assumption:** `JEV` = Jev AI router in `swarm_sdk.core.jev_router`, not a typo for Jira.

---

## 11. Codebase analysis

### Affected modules

| Path | Role |
| --- | --- |
| `src/swarm_sdk/orchestrator/` | Plan spawn, wave execution, workers |
| `src/swarm_sdk/core/jev_router.py` | Noul / Score / Choice |
| `src/swarm_sdk/orchestrator/low_swarm.py` | Reference LangGraph + Jev (coder-centric today) |
| `src/swarm_sdk/server/graphs.py` | LangGraph Server `plan` factory |
| `src/swarm_sdk/agents/manifest.py` | Agent registry |
| `Agents/coordination.yaml` | Task board |
| `Agents/SKILLS.md` | Persona catalog |
| `WebSearch/cowork_agents.py` | Deterministic pipeline pattern C |

### Patterns discovered

- **API:** `swarm-api` / gRPC delegate to `run_plan` with `max_concurrency`.
- **Parallelism:** `Main/config/swarm.yaml` → `parallelism.max_concurrency`.
- **Tests:** `tests/test_jev_router.py`, `Agents/benchmark/tests/test_model_routes.py`.
- **Contracts:** JSON output per `Agents/*/AGENTS.md`; no TEMPLATE map in persona files.

### Reference implementations

- Parallel coworkers: `WebFetch` / `Normalizer` / `Persister` wave barriers in `WebSearch/`.
- Jev + graph: `LowSwarmEngine._build_graph`.
- Full swarm docs: `Documents/LangSwarm.md` §9.

### Test locations

- `tests/test_jev_router.py` — Jev unit tests
- `Agents/benchmark/tests/` — integration and model routes
- `Agents/benchmark/Tasks/websearch_tools/` — pipeline tasks

---

## 12. Linked tickets (proposed — create in Jira under epic)

| Key | Summary | Type | Notes |
| --- | --- | --- | --- |
| SWARM-JEV-1 | JevWorkerMixin: noul+score on PlanStep execution | Story | worker.py |
| SWARM-JEV-2 | ChoiceDecision when agent ambiguous | Story | spawn validation |
| SWARM-JEV-3 | Extend `_CANDIDATE_KEYWORDS` for all personas | Task | jev_router.py |
| SWARM-JEV-4 | Benchmark: parallel two-Coder wave plan | Story | benchmark |
| SWARM-JEV-5 | `swarm.yaml` feature flag + docs | Task | LangSwarm.md |
| SWARM-JEV-6 | coordination.yaml exemplar parallel graph | Task | Agents |

*Replace keys when epic exists in Jira; use JQL `"Epic Link" = SWARM-JEV`.*

---

## Next steps

1. **Confirm epic in Jira** (key, title, Confluence path) — required by `/create-epic-plan` Phase 0.
2. Publish this doc to Confluence when approved, or keep at `Documents/epics/SWARM-JEV-PARALLEL-OVERVIEW.md`.
3. Run `/create-implementation-plan Documents/epics/SWARM-JEV-PARALLEL-OVERVIEW.md` after confirmation.
