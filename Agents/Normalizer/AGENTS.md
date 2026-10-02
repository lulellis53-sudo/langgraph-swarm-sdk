# Normalizer

Deterministic cowork agent in the three-stage web pipeline:
**WebFetch (Playwright) -> Normalizer (normalize + dedupe) -> Persister (SQLite)**.

## Contract

- Role: `normalize_dedupe`
- Capabilities: `selectolax_extract`, `normalize_text`, `blake2b_dedupe`
- Stage: selectolax extraction + normalize_text + content dedupe
- Executed through `WebSearch/cowork_agents.py::run_cowork_pipeline`
  (LangGraph Swarm SDK, Pattern C wave-barrier: wave 0 parallel fetch,
  wave 1 normalize + blake2b dedupe, wave 2 SQLite INSERT OR IGNORE).
- Deterministic: no LLM call. Heavy payloads (HTML bytes, extracted docs)
  travel in the factory-bound scratchpad; the transcript only carries
  short summaries.
- Secrets: none.
