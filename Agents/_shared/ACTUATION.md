# Swarm specialist actuation (DARS · ReAct · Reflection · SWE)

Every persona in `Agents/*/AGENTS.md` uses the same **four-layer** control loop. Full
definitions, routing tables, and work-type examples live in
[`../AgentMethods.md`](../AgentMethods.md).

## Combined control loop

```text
                    [ inbound task from plan / handoff ]
                                    │
                                    v
              +-------------------------------------+
              | DARS: classify scope, impact, risk, |
              | uncertainty, verification cost      |
              +------------------+------------------+
                                 │
                    +------------+------------+
                    |            |            |
                   L1           L2–L3        L4
              bounded local   multi-step   blocked /
              direct check    + evidence   needs_input
                    |            |            |
                    +------------+------------+
                                 │
                                 v
              +-------------------------------------+
              | ReAct: observe → record evidence → |
              | one bounded action → check outcome  |
              +------------------+------------------+
                                 │
                         check passed?
                    +------------+------------+
                   yes                        no
                    |                         |
                    v                         v
              +-----------+          +------------------+
              | SWE handoff|          | Reflection:      |
              | (verify +  |          | classify failure,|
              |  report)   |          | one focused fix, |
              +-----------+          | re-run check     |
                                       +--------+---------+
                                                │
                                    budget exhausted?
                                    → blocked + evidence
```

| Layer | Question this role must answer |
| --- | --- |
| **DARS** | Is this L1–L4 for *my* task type? (see AgentMethods §1 and §5.) |
| **ReAct** | What did I observe, what did I do, what check proves progress? |
| **Reflection** | If a check failed, what *class* of failure and what single correction? |
| **SWE** | Specify → locate → plan → act (if permitted) → verify → review → handoff JSON |

## Read-only vs write boundaries

| Boundary | Agents | SWE “implement” stage |
| --- | --- | --- |
| **Read-only** | Researcher, Reviewer, Security (audit), DeepResearch, RAG (retrieve) | Analysis + deliverable + JSON contract only |
| **Write** | Coder, Refactor, Tester, Documenter, DataEngineer, … | Smallest complete change + gate |
| **Deterministic (no LLM)** | WebFetch, Normalizer, Persister | Fixed pipeline; ReAct = reconcile counts |

## Rules (all personas)

1. One failed verification → classify → one deliberate correction (no blind retries).
2. Never weaken lint, types, or tests to get green without a named rule.
3. Never paste secrets; report path/pattern only (see `Agents/Security/AGENTS.md`).
4. Emit the JSON **output contract** from your `AGENTS.md` when the task completes.
5. `blocked` and `needs_input` are valid outcomes when evidence or access is missing.

## Universal pre-handoff checklist

- [ ] DARS level chosen and documented in `notes` when non-obvious
- [ ] Required checks for this role actually run (not assumed)
- [ ] Output contract populated; status matches reality
- [ ] Handoff names the next agent or gate when work continues elsewhere

See also [`COMMON.md`](./COMMON.md) (TEMPLATE §3·§5·§7·§10) and [`TEMPLATE.md`](../TEMPLATE.md) §8 decision-path examples.
