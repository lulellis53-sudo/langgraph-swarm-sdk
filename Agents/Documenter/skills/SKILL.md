---
name: DocumenterSkill
description: "Specialized skill and capabilities specification for Documenter."
---

# Documenter Skill Specification

> **Authoritative Specification**: Operational skill directives and execution workflows for `Agents/Documenter`.

## 1. Overview
Defines core capabilities, domain procedures, and tool usage contracts for the `Documenter` agent persona.

## 2. Execution Protocol
1. **Intake & Scope Validation**: Verify inputs against `agent.yaml` task contracts.
2. **Deterministic Execution**: Apply domain methods adhering to Google Style Guidelines.
3. **Evidence Handoff**: Emit structured outputs and update task ledgers.

## 3. OpenAI document templates

Use a template when the requested output benefits from a structured document
layout or the user names a template. Skill folders use the exact skill name:

- [`artifact-template-design-report`](artifact-template-design-report/SKILL.md)
- [`artifact-template-experiment-analysis`](artifact-template-experiment-analysis/SKILL.md)
- [`artifact-template-investment-committee-memo`](artifact-template-investment-committee-memo/SKILL.md)
- [`artifact-template-legal-memorandum`](artifact-template-legal-memorandum/SKILL.md)
- [`artifact-template-minimal-letterhead`](artifact-template-minimal-letterhead/SKILL.md)
- [`artifact-template-strategy-memorandum`](artifact-template-strategy-memorandum/SKILL.md)
- [`artifact-template-system-design`](artifact-template-system-design/SKILL.md)

Read the implementation or primary source before writing technical claims.
Keep supplied template reference files unchanged.
