# Agent Tools Specification: AgentCompacting

> **Authoritative Specification**: Tooling catalog, API endpoints, free model providers, and memory persistence mechanisms for `AgentCompacting`.

---

## 1. Free-Model Endpoints & API Specifications

`AgentCompacting` leverages free LLM backends to compress transcripts into AntigravityBrain summaries with zero inference cost:

### 1.1 Local Ollama (Zero-Cost, 100% Offline)
- **Endpoint**: `http://localhost:11434/api/generate` or `http://localhost:11434/v1/chat/completions`
- **Recommended Models**: `qwen2.5:7b`, `llama3.2:3b`, `mistral:7b`, `gemma-2:2b`
- **Authentication**: None required.
- **Payload Example**:
  ```bash
  curl -s http://localhost:11434/api/generate -d '{
    "model": "qwen2.5:7b",
    "prompt": "Summarize transcript into AntigravityBrain layout...",
    "stream": false
  }'
  ```

### 1.2 Google Gemini Flash Free Tier (1M Context Window)
- **Endpoint**: `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=${GEMINI_API_KEY}`
- **Free Quota**: 15 requests/minute, 1,500 requests/day, 1,000,000 tokens context window.
- **Authentication**: `GEMINI_API_KEY` or `GOOGLE_API_KEY` (Free tier from Google AI Studio).
- **Advantage**: Handles massive sessions with tens of thousands of tokens in a single shot without chunking.

### 1.3 Groq Free Tier (Ultra-Fast 500+ tok/s)
- **Endpoint**: `https://api.groq.com/openai/v1/chat/completions`
- **Recommended Models**: `llama-3.3-70b-versatile`, `llama-3.1-8b-instant`
- **Free Quota**: 30 requests/minute, 14,400 requests/day.
- **Authentication**: `GROQ_API_KEY` (Free tier from console.groq.com).

### 1.4 OpenRouter Free Models
- **Endpoint**: `https://openrouter.ai/api/v1/chat/completions`
- **Free Models**: `meta-llama/llama-3.3-70b-instruct:free`, `google/gemini-2.0-flash-exp:free`, `deepseek/deepseek-r1:free`
- **Authentication**: `OPENROUTER_API_KEY` (Requires only free account signup).

---

## 2. Built-in Compactor Engine (`compact_session.py`)

`AgentCompacting` includes a standalone, zero-dependency Python compaction utility:

### Location:
[`Agents/Extra/AgentCompacting/compact_session.py`](compact_session.py)

### Capabilities:
1. **JSONL Transcript Parsing**: Streams and parses conversation logs line-by-line without high RAM overhead.
2. **Event & Request Distillation**: Automatically isolates `USER_INPUT`, `USER_EXPLICIT` prompts, and executed tool calls.
3. **Adaptive Provider Routing**:
   - Checks if local Ollama daemon is reachable.
   - Falls back to Gemini/Groq free tier if keys exist.
   - Falls back to deterministic rule-based extractive summarization if no LLM runtime is available.
4. **AntigravityBrain Format Generation**: Emits `<CONTEXT_SUMMARY>` with the exact 6-part schema.
5. **Memory Directory Storage**: Writes to `memory/sessions/<session_id>.md` and appends to `memory/index.md`.

---

## 3. Operational CLI Recipes

```bash
# Basic run with automatic provider detection
python -m AgentCompacting.compact_session \
  --transcript ~/.gemini/antigravity-cli/brain/<conv-id>/.system_generated/logs/transcript.jsonl \
  --memory-dir ./memory

# Explicitly use local Ollama with qwen2.5
python -m AgentCompacting.compact_session \
  --transcript ~/.gemini/antigravity-cli/brain/<conv-id>/.system_generated/logs/transcript.jsonl \
  --provider ollama \
  --model qwen2.5:7b \
  --memory-dir ./memory

# Deterministic zero-token fallback
python -m AgentCompacting.compact_session \
  --transcript ~/.gemini/antigravity-cli/brain/<conv-id>/.system_generated/logs/transcript.jsonl \
  --provider algorithmic \
  --memory-dir ./memory
```

---

## 4. Memory Storage Hierarchy

```text
/memory/
├── index.md                      # Global registry of compacted sessions
└── sessions/
    ├── 7b45c73a-d163-4a80.md     # AntigravityBrain formatted session summary
    └── 3a7e04f3-d852-4e8b.md     # Past compacted session record
```
