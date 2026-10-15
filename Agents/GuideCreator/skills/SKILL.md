---
name: GuideCreatorSkill
description: Specialist agent creation and guideline synthesis skill for GuideCreator agent.
---

# GuideCreator Skill Guide

> **Purpose**: Provide the **GuideCreator** agent with template instantiation rules, prompt compression algorithms, and manifest validation protocols.

---

## 1. Guideline Synthesis Procedures
- Load canonical templates from [`AgentMethods.md`](../../AgentMethods.md), [`TEMPLATE.md`](../../TEMPLATE.md), [`TEMPLATE1.md`](../../TEMPLATE1.md), and [`TEMPLATE3.md`](../../TEMPLATE3.md).
- Assign strictly one primary execution method per function type according to the 1-to-1 taxonomy matrix.
- Verify manifest syntax using `swarm_sdk.agents.validate`.
