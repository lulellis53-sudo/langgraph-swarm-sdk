# Autonomous Agent Methods Reference (`methods.md`)

> **Authoritative Specification**: Reusable Agent Execution Methods for `CreatorAgent`.
> **Source Foundation**: Consolidated from `AgentMethods.md` and `AgenticCreator`.

---

## 1. DARS (Discover, Analyze, Reflect, Synthesize) Router

DARS routes incoming agent tasks based on scope, difficulty, and risk:

```text
[Inbound Task] ──► [Scope Triage] ──► [L1 - L4 Routing] ──► [Bounded Action]
```

- **Level 1 (Direct Query / L1)**: 1-step direct factual query or known symbol lookup (`rg`, `bat`). No planning overhead.
- **Level 2 (Standard Playbook / L2)**: Routine tasks adhering to known file patterns. Single-turn execution.
- **Level 3 (Multi-File / Architecture / L3)**: Non-trivial multi-file refactor, cross-module synchronization, or database migrations. Requires in-memory plan and 3-7 verifiable criteria.
- **Level 4 (Outward-Facing / Irreversible / L4)**: Destructive filesystem modifications, credentials, or production deploys. Requires explicit confirmation gates.

---

## 2. ReAct (Reason + Act Loop)

A bounded loop that prevents wandering and token exhaustion:

`OBSERVE -> DECIDE -> ACT -> VERIFY -> STOP`

1. **Observe**: Read only the necessary lines using slice notation (`view_file`). Never dump entire files without justification.
2. **Decide**: Choose the smallest single reversible step that advances the task.
3. **Act**: Execute bounded tool call.
4. **Verify**: Check actual exit code 0 and command output.
5. **Stop**: Terminate immediately once acceptance criteria are evidenced.

---

## 3. Reflection & Recovery Ladders

When a command, test, or tool call fails:
- **Zero Identical Retries**: Never rerun the exact same failed command without a changed hypothesis.
- **4-Tier Diagnostic Ladder**:
  1. *Syntax / Flag check*: Inspect `--help` and verify flag spelling against installed binary.
  2. *Environment / Path check*: Verify active virtualenv, binary paths in PATH, and sandbox boundaries.
  3. *Hypothesis Mutation*: Change one variable (query terms, input payload, or algorithm formulation).
  4. *Circuit Breaker*: Stop after 3 unsuccessful approaches and report concrete blockers.

---

## 4. SWE Workflow (Software Engineering Delivery)

Standardized software implementation sequence:
1. **Specify**: State the expected behavior and acceptance criteria.
2. **Locate**: Find exact symbols, callers, and tests via `rg` / `fd`.
3. **Test-First**: Inspect existing tests or draft reproduction case before touching code.
4. **Implement**: Smallest coherent diff using direct in-place edits (`replace_file_content`).
5. **Lint & Typecheck**: Run project linter (`ruff`, `biome`) and static type checker (`ty`, `mypy`).
6. **Verify**: Execute targeted unit test first, then inspect `git diff`.

---

## 5. ACT Protocol (Anchor, Calculate, Test) for Math & Numerics

1. **Anchor**: Declare theoretical definitions, variable types, units, and boundary invariants.
2. **Calculate**: Execute deterministic compute via Python (`SymPy`, `NumPy`, `Polars`) rather than guessing numbers.
3. **Test**: Cross-validate against independent mathematical oracles or known boundary conditions.

---

## 6. Corrective RAG (CRAG) for Knowledge & Research

1. **Decompose**: Split multi-hop user questions into atomic search queries.
2. **Retrieve**: Query Context7 first, then DuckDuckGo MCP / Tavily.
3. **Evaluate**: Score retrieved passage relevance. If confidence $< 0.65$, fall back to secondary sources.
4. **Synthesize**: Ground all claims with clickable, verified URLs.
