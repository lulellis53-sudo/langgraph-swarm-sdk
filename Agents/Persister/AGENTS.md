# Persister

Deterministic cowork agent in the three-stage web pipeline:
**WebFetch (Playwright) -> Normalizer (normalize + dedupe) -> Persister (SQLite)**.

## Contract

- Role: `store_documents`
- Capabilities: `sqlite_store`, `url_digest_dedupe`
- Stage: SQLite documents table, INSERT OR IGNORE
- Executed through `WebSearch/cowork_agents.py::run_cowork_pipeline`
  (LangGraph Swarm SDK, Pattern C wave-barrier: wave 0 parallel fetch,
  wave 1 normalize + blake2b dedupe, wave 2 SQLite INSERT OR IGNORE).
- Deterministic: no LLM call. Heavy payloads (HTML bytes, extracted docs)
  travel in the factory-bound scratchpad; the transcript only carries
  short summaries.
- Secrets: none.
