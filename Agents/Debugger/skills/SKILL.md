---
name: DebuggerSkill
description: Failure diagnosis, bisection, root-cause isolation, and review-remediation skill for Debugger agent.
---

# Debugger Skill Guide

> **Purpose**: Provide root-cause diagnosis protocols, git bisection procedures, and review finding remediation rules for **Debugger**.

---

## Operating Protocols

1. **Reproduction Before Diagnosis**: Never theorize without a minimal, deterministic reproduction.
2. **Review Finding Remediation**: When applying `CodeReview` findings, address CRITICAL and HIGH severity findings first with minimal targeted diffs.
3. **Verification**: Confirm exit code `0` on targeted tests before claiming fix completion.
