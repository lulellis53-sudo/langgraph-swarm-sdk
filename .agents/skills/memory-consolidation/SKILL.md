---
name: memory-consolidation
description: Use when persisting, updating, or synthesizing cross-session memory, project conventions, user preferences, and retrospective lessons learned into long-term configuration files (like GEMINI.md, AGENTS.md, or episodic memory stores).
---

# Memory Consolidation

## Overview

Memory consolidation is the disciplined process of converting ephemeral conversational discoveries, user corrections, bug post-mortems, and architectural conventions into permanent, actionable project guidelines. Without active consolidation, agents repeat identical debugging failures across conversations and lose alignment with human developer preferences.

**Core principle:** If a failure was resolved or a preference was stated once, it must be codified into persistent memory so it never needs to be taught again.

---

## The Tri-Tier Memory Model

```
       ┌────────────────────────────────────────────────────────┐
       │                 TRI-TIER MEMORY MODEL                  │
       ├────────────────────────────────────────────────────────┤
       │  [Tier 1] Working Memory (Ephemeral conversation turns)│
       │  [Tier 2] Episodic Memory (Task logs, debug transcripts)│
       │  [Tier 3] Semantic / Procedural Memory (GEMINI.md,     │
       │           AGENTS.md, conventions, persistent rules)    │
       └────────────────────────────────────────────────────────┘
```

1. **Working Memory**: In-flight token context window. Volatile; lost on session restart.
2. **Episodic Memory**: Stored session transcripts, task execution logs, and benchmark records.
3. **Semantic / Procedural Memory**: Explicit, consolidated guidelines (`GEMINI.md`, `AGENTS.md`, `rules/`) that are automatically injected into future agent sessions.

---

## When to Consolidate Memory

**Trigger immediately when:**
- The user corrects the agent's behavior (e.g. "Do not use X", "Always format with Y").
- A non-trivial bug or build failure was root-caused after multiple iterations.
- An environment constraint or workaround was discovered (e.g. "macOS sandbox blocks `mkdir .agents`").
- A new architectural standard or library pattern was adopted for the repository.

**Do NOT consolidate:**
- Ephemeral, one-off user inputs (e.g. "change this specific button to blue").
- Speculative assumptions not confirmed by test evidence or user approval.
- Redundant rules that are already stated in global defaults.

---

## The Consolidation Lifecycle

```
  [User Correction / Debug Discovery]
                  │
                  ▼
         [Phase 1: Ingestion]
         - Capture root cause & exact constraint
                  │
                  ▼
        [Phase 2: Deduplication]
        - Check existing GEMINI.md / AGENTS.md
        - Ensure rule is not already covered
                  │
                  ▼
        [Phase 3: Generalization]
        - Strip conversational chatter
        - Format as a concise, imperative rule
                  │
                  ▼
       [Phase 4: Conflict Resolution]
        - Reconcile with existing instructions
        - Priority: Project Rule > User Global > Default
                  │
                  ▼
       [Phase 5: Commit to File]
        - Write update to target rule file (GEMINI.md)
        - Keep document under max line bounds
```

---

## Consolidation Rules & Style Guidelines

1. **Imperative, Non-Chatty Language**: Write rules as clear, direct commands:
   - *Bad*: "The user prefers that we avoid arbitrary markdown files because it clutters things up."
   - *Good*: "Never invent or generate `.md` files with arbitrary names. Only create markdown files explicitly ordered by the user."
2. **Include the 'Why' & Failure Symptom**: State the concrete failure mode when relevant:
   - *Example*: "Do not assume GNU `sed` or Linux `/proc`; macOS BSD userland requires portable syntax."
3. **Anti-Bloat Discipline**:
   - Merge overlapping rules rather than appending endless bullet points.
   - Periodically prune obsolete constraints when tools or dependencies change.
   - Enforce document boundaries (e.g. keeping `GEMINI.md` structured and under 400 lines).

---

## Checklist: Before Committing Consolidated Memory

- [ ] Does the new rule solve a proven, recurring problem?
- [ ] Is it placed in the correct hierarchical file (`GEMINI.md` for project rules, `AGENTS.md` for agent roles)?
- [ ] Does it avoid contradicting existing higher-priority guidelines?
- [ ] Is it phrased concisely without narrative filler?
- [ ] Has the file diff been inspected to ensure no unrelated instructions were corrupted?
