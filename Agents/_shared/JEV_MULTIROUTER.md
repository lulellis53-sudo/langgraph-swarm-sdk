# Jev multirouter (swarm-wide)

TypeSafe **Jev** supplies typed snap judgments (Noul, Score, Choice). **Code owns the
workflow**; Jev does not implement tasks or replace pytest. Implementation:
`Core/Sdk/swarm_sdk/core/jev_router.py`, spawn hint `system_one.py`, plan gate
`orchestrator/jev_gate.py`. Golden routing cases:
`Core/benchmark/tasks/jev_agent_routing/cases.py`.

## Thresholds (tune in code, not in prompts)

| Signal | Use | Default gate |
| --- | --- | --- |
| Noul | Block destructive / exfil patterns | `decision == false` → blocked step |
| Choice `confidence` | Auto-assign agent | Act if ≥ **0.60**; else confirm or Orchestrator |
| Choice accuracy (CI) | Local fallback quality | ≥ **85%** on golden cases |
| Choice latency | Local fallback SLA | p50 ≤ **35 ms** |
| Score `model_tier` | `flash_lite` / `flash` / `pro` | OpenCL, multi-file, concurrency → **pro** |
| Registry route | ModelDelegate | `think_level` match, then lowest `priority` |

Hosted System One (optional): `TYPESAFE_API_KEY` or `JEV_API_KEY` — hints only for spawn;
step text with repo content stays on **local** Noul/Score in `jev_gate`.

## ASCII multirouter (all personas)

```text
+====================================================================================+
|                         SWARM JEV MULTIROUTER                                        |
+====================================================================================+

                         [ inbound goal / plan step / handoff ]
                                         |
                                         v
                          +---------------------------+
                          | LAYER 0: CODE DENYLIST    |
                          | destructive rm, pipe|sh,   |
                          | secret exfil patterns     |
                          +---------------------------+
                               | pass          | fail
                               v               v
                          +-----------+   +------------------+
                          | continue  |   | BLOCK (no Jev    |
                          +-----------+   |  override)       |
                               |          +------------------+
                               v
                          +---------------------------+
                          | LAYER 1: NOUL             |
                          | Safe to run this task?    |
                          +---------------------------+
                               | yes           | no
                               v               v
                          +-----------+   +------------------+
                          | continue  |   | blocked_output   |
                          +-----------+   +------------------+
                               |
                               v
                          +---------------------------+
                          | LAYER 2: CHOICE           |
                          | Which agent owns work?    |
                          | (SKILLS.md roster)        |
                          +---------------------------+
                               |
              +----------------+----------------+
              | conf < 0.60    | conf OK        |
              v                v
        confirm /           selected agent
        Orchestrator              |
                                  v
                          +---------------------------+
                          | LAYER 3: SCORE            |
                          | Model tier for step       |
                          +---------------------------+
                                  |
                                  v
                          +---------------------------+
                          | LAYER 4: MODEL REGISTRY   |
                          | ModelDelegate route_task  |
                          | + fallback chain          |
                          +---------------------------+
                                  |
                                  v
                          +---------------------------+
                          | LAYER 5: PERSONA          |
                          | DARS / ReAct / SWE in     |
                          | this agent's AGENTS.md    |
                          +---------------------------+
```

## Choice roster (primary specialists)

| Agent | Route when goal emphasizes |
| --- | --- |
| Planner | Decompose, waves, dependencies, coordination |
| Researcher | Investigate, synthesize, read-only evidence |
| Coder | Implement, refactor, features, OpenCL/code moves |
| Tester | Pytest, coverage, specs (not sole owner of refactors) |
| Debugger | Tracebacks, reproduce, root cause |
| Documenter | README, docstrings, changelog |
| DevOps | CI, pixi, docker, deploy |
| Security | Audit, CVE, credentials, vulns |
| DataEngineer | Pipelines, ETL, qdrant/sqlite ingest |
| Caching | Redis, semantic cache, TTL |
| MLSpecialist | Embeddings, faiss, RAG models |
| Optimizer | Profile, benchmark, tune, latency |
| Reviewer | PR/diff review before merge |
| Orchestrator | Assign/track only — not implement |
| Judge | Scorecards, benchmarks audit, `judge_models` |
| ModelDelegate | Registry route / GPU embed / math dispatch |

## Primitive cheat sheet

| Need | Jev type | Branch on |
| --- | --- | --- |
| Pick one agent | Choice | `selected_choice`; gate with `confidence` |
| Pick model tier | Score | `model_tier` / threshold on `score` |
| Yes/no safe | Noul | `decision` or `noul > threshold` (no `confidence` on Noul) |

Do not use one LLM call to pick labels when Choice/Noul/Score fit. Combine multiple
Nouls in code (min for safety flags, max for “any red flag”).

## Reflect, backward paths, autolearn

After Layer 5, every persona runs a **reflection** gate; failures rewind to the earliest
wrong layer (MR2–MR4 for routing/registry, D2–D4 for DARS). Misroutes and low-confidence
routes append to `Agents/Judge/Benchmark/routing_experience.jsonl` for tuned keywords in
`jev_router.py` / `cases.py`.

Full algorithm and diagram:
[`JEV_REFLECT_AUTOLEARN.md`](JEV_REFLECT_AUTOLEARN.md).

## Verify routing

```bash
pixi run python -m Core.benchmark.run --task jev_agent_routing
pixi run python -m Core.benchmark.jev_autolearn --report
pixi run python -m pytest Core/tests/test_jev_swarm_routing.py -q
```
