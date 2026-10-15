---
name: AgentCompactingSkill
description: "Master session compaction and memory summarization skill. Ingests session transcripts, executes free-model or algorithmic summarization, and stores AntigravityBrain summaries into /memory."
---

# AgentCompacting Skill Specification

## 1. Overview
The `AgentCompactingSkill` empowers `AgentCompacting` to parse active or completed agent session transcripts, compress conversation history, and extract salient facts into the standard AntigravityBrain summary format.

## 2. Capabilities
1. **Transcript Stream Parsing**: Ingests `.jsonl` session logs, parsing `USER_INPUT`, `USER_EXPLICIT`, tool actions, and model thinking blocks.
2. **Free-Model Routing**: Dynamically selects between local Ollama (`qwen2.5:7b`), Gemini Flash free tier (`gemini-2.0-flash`), Groq free tier (`llama-3.3-70b-versatile`), and deterministic algorithmic fallback.
3. **AntigravityBrain Format Synthesis**: Emits the standard `<CONTEXT_SUMMARY>` block encompassing User Requests, Task Overview, Progress, Key Findings, Active Context, Next Steps, and Commitments.
4. **Memory Hierarchy Persistence**: Writes markdown records into `/memory/sessions/<session_id>.md` and registers entries in `/memory/index.md`.
