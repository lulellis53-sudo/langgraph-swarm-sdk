## Agentic workflow

Source: [`/AgentMethods.md`](/AgentMethods.md) · [`/TEMPLATE.md`](/TEMPLATE.md)

```text
[Intake: goal, scope, limits, acceptance criteria]
                    |
                    v
         +----------------------+
         | Clear, permitted,    |
         | in role?             |
         +----------+-----------+
              No   |   Yes
              v    v
           blocker  +----------------------+
                    | DARS classify L1–L4  |
                    +----------+-----------+
                               |
              +----------------+----------------+
              | L4 ask/block | L1 local | L2/L3 deep
              v              v          v
         +----------------------------------------+
         | Vertical: retrieval | math | code |   |
         | review | database | SWE | specialist |
         +--------------------+-------------------+
                              |
                              v
         +----------------------------------------+
         | Execute: direct | chain | parallel |  |
         | orchestrator | ReAct observe-act      |
         +--------------------+-------------------+
                              |
                              v
         +----------------------------------------+
         | Domain verify (tests, audit, oracle) |
         +--------------------+-------------------+
                    pass |          | fail
                         v          v
                    handoff JSON   Reflection:
                                   one fix, rerun
                                   same check (max 2)
                                   -> else blocked
```

**This persona:** Primary: **DARS + ReAct** — follow this persona's decision tree when scope matches `Agents`.

**Backward / reflection:** failed check → classify (missing evidence | wrong plan | wrong route) → rewind to earliest wrong stage → one bounded fix → rerun the **same** check. Max **2** rewinds, then `blocked` / `needs_input` with evidence.

## Master agentic workflow (all personas)

Each `AGENTS.md` embeds this ASCII gate from `TEMPLATE.md` / `AgentMethods.md`:

```text
[Intake] → role OK? → DARS L1–L4 → vertical (research|math|code|review|DB|SWE)
         → execute (ReAct / chain / parallel) → domain verify
         → pass: handoff JSON | fail: Reflection (max 2 rewinds) → blocked
```

Re-sync persona sections after editing methods:

```bash
python3 Agents/_shared/sync_agentic_workflow.py
```
