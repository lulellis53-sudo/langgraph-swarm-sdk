# Jev reflect, backward paths, and autolearn

Extends the forward multirouter in [`JEV_MULTIROUTER.md`](JEV_MULTIROUTER.md). **Code owns rewinds**
and the experience buffer; Jev supplies **Noul/Score/Choice** signals on each pass, not prose
plans. Persona DARS backward rails (B1–B4) map onto multirouter **layers** below.

## Budgets (shared across agents)

| Control | Limit |
| --- | --- |
| Multirouter rewind | **2** per task (then `needs_input` or Orchestrator) |
| Persona DARS replan | **2** (Coder/Judge contracts) |
| Research rounds | **3** to close unknowns |
| Solve retries | **3** per subgoal, **same check** after each fix |
| Autolearn promotion | Only when regression gate passes (see algorithm) |

## ASCII: forward + reflection + backward

```text
+====================================================================================+
|              JEV MULTIROUTER + REFLECT + BACKWARD + AUTOLEARN                        |
+====================================================================================+

 [inbound goal] ──► Layers 0–5 (see JEV_MULTIROUTER.md) ──► persona DARS → handoff JSON
                                        |
                                        v
                          +---------------------------+
                          | REFLECT (hostile critic)  |
                          | - tests/evidence present? |
                          | - claims tagged?          |
                          | - Jev vs pytest: pytest   |
                          |   wins on conflict        |
                          +---------------------------+
                               | pass
           +-------------------+-------------------+
           | fail              |                   |
           v                   v                   |
  +----------------+    +----------------+          |
  | name earliest  |    | APPROVE / done |          |
  | wrong stage    |    +----------------+          |
  +----------------+                               |
           |                                       |
     +-----+-----+-----+-----+                     |
     |     |     |     |     |                     |
    MR2   MR3   MR4   D2    D3/D4                  |
  Choice Score Reg. Solve Analyse/Discover          |
     |     |     |     |     |                     |
     +-----+-----+-----+-----+---------------------+
           |
           v (rewinds += 1; log reason + changed input)
     < rewinds < 2 ? ──no──► NEEDS_REVISION / blocked
           |
          yes
           │
           v
                          +---------------------------+
                          | AUTOLEARN (on measured    |
                          |  failure or Δ benchmark)  |
                          +---------------------------+
                                       |
                                       v
                          append routing_experience.jsonl
                          tune cases.py / jev_router keywords
                          (human review; no silent prod edit)
```

### Multirouter backward map (MR*)

| Tag | Symptom | Rewind to | Owner |
| --- | --- | --- | --- |
| **MR2** | Wrong agent; low Choice confidence; second agent P ≥ 0.25 | Layer 2 Choice (+ Orchestrator confirm) | Orchestrator / Planner |
| **MR3** | Timeouts, quality mismatch, cost blowout | Layer 3 Score → re-tier | ModelDelegate hint |
| **MR4** | Provider 4xx/5xx, breaker open | Layer 4 fallback chain | ModelDelegate |
| **D2** | Fixable in current persona; one criterion failed | Persona Solve only | This agent |
| **D3** | Wrong “done” criteria or tier | Persona Analyse | This agent |
| **D4** | Missed files, callers, claims | Persona Discover | This agent |
| **B1** | Judge IMPROVE returned new target | Full Discover | Judge → specialist |

Never rewind by repeating the **same** action unchanged (same flag, same patch, same query).

## Self-reflection checklist (every agent, before `done`)

1. **Evidence**: every acceptance criterion has a command output or `file:line` citation.
2. **Routing**: if Choice confidence was &lt; 0.60, handoff says `needs_input` or names the second-choice agent.
3. **Safety**: Noul block or code denylist hit is never overridden by model text.
4. **Honesty**: unrun checks listed under `limitations`; no inflated benchmarks.

Judge runs the full R1–R6 list; other agents run items 1–4 unless their contract adds more.

## Autolearn algorithm (routing + benchmarks)

Measured loop — no LLM self-edit of `jev_router.py` without a failing test.

```text
1. RUN golden set (Core/benchmark/tasks/jev_agent_routing/cases.py)
2. FOR each case (goal, expected_agent):
     decision = evaluate_choice(goal, roster)
     IF decision.selected != expected OR decision.confidence < REVIEW_CONFIDENCE_BELOW:
        RECORD {goal, expected, actual, confidence, timestamp}
        CLASSIFY cause: missing_keyword | substring_trap | wrong_roster | model_error
3. COMPUTE accuracy, p50 latency; FAIL gate if below MIN_ROUTING_ACCURACY or MAX_CHOICE_P50_MS
4. IF regression gate passes on agent benchmark (Judge harness):
        learning_gain = 0.40*Δaccuracy - 0.25*Δlatency - 0.20*Δtokens - 0.15*Δmemory
        APPEND experience buffer with verdict BENCHMARK_PROMOTED | REJECTED
5. HUMAN (or CreatorAgent task): patch cases.py / _CANDIDATE_KEYWORDS from RECORD bucket
6. RE-RUN step 1 until accuracy recovers or budget exhausted
```

Implementation: `Core/benchmark/jev_autolearn.py`  
Buffer: `Agents/Judge/Benchmark/routing_experience.jsonl`  
Agent metrics buffer (existing): `Agents/Judge/Benchmark/experience_buffer.jsonl`

## Jev questions on reflect pass (one System One call when key present)

Put **evidence JSON** in `state`, not the desired verdict:

| Question id | Type | Purpose |
| --- | --- | --- |
| `routing_ok` | Noul | Golden label matches Choice |
| `confidence_ok` | Noul | Choice confidence ≥ act threshold |
| `tier_ok` | Noul | Score tier matches task class (optional) |
| `rewind_target` | Choice | `none` \| `choice` \| `score` \| `registry` \| `discover` \| `analyse` \| `solve` |

If the key is absent, use local metrics only; do not invent Jev scores.

## Verify

```bash
pixi run python -m Core.benchmark.run --task jev_agent_routing
pixi run python -m Core.benchmark.jev_autolearn --report
```
