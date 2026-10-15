---
name: CodeReviewSkill
description: Specialist audit skill for CodeReview agent enforcing two-stage critique (BitsAI-CR), reachability analysis, GIL-free concurrency checking, and security smell detection.
---

# CodeReview Skill Guide

> **Purpose**: Provide the **CodeReview** agent with static analysis checklists, security taint tracking rules, and concurrency verification procedures.

---

## 1. Two-Stage Critique Audit Checklist

### Stage 1: Broad Defect Scanning
- **Correctness**: Off-by-one errors, unhandled `None`/`null` dereferences, silent exception swallowing.
- **Security**: Injection (SQL, Command, Log), hardcoded credentials, unsafe deserialization (`pickle`, `eval`).
- **Concurrency**: Shared mutable state in Python free-threaded (GIL-free) runtime, un-atomic multi-step state updates, lock order inversion.
- **API Contracts**: Missing Pydantic v2 schemas on public endpoint payloads.

### Stage 2: Precision & Reachability Filter
- **Reachability Verification**: Is the untrusted input source reachable via public routes or internal callers? If no, discard or downgrade severity to LOW.
- **Linter Suppression**: Is the finding enforceable by `ruff` or `pyright`? If yes, suppress text comment and rely on mechanical gate.
