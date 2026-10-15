---
name: TokenSaverSkill
description: Token reduction, AST prompt compression (LLMLingua-2), semantic caching, and throughput optimization skill for TokenSaver agent.
---

# TokenSaver Skill Guide

> **Purpose**: Provide prompt compression algorithms, two-tier caching strategies, and latency/RPM reduction rules for **TokenSaver**.

---

## 1. Prompt Compression & Token Reduction Matrix

| Technique | Description | Typical Savings | Verification |
| :--- | :--- | :--- | :--- |
| **AST Pruning** | Remove unneeded boilerplate code and comments before sending to LLM | **20-40% Tokens** | `uv run ruff check` |
| **LLMLingua-2** | Token-level perplexity compression for long context prompts | **30-60% Tokens** | Output quality check |
| **Semantic Caching** | SHA-256 exact hit ($< 2\text{ms}$) + INT8 vector similarity | **100% Tokens (on hit)** | `retrieval/cache.py` |
| **Batching** | Combine independent subagent prompts into single wave call | **30-50% RPM** | `coordination.yaml` wave audit |
