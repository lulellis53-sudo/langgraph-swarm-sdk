# AGENTS.md — WebSearch

3-stage search pipeline: **frontend** (search providers) → **midend** (crawl/scrape) → **backend** (extract/normalize/store). Python package lives at **`Tools/WebSearch/`** (`import WebSearch`); lane branch **`feature/websearch`**, worktree **`../Workspace-WebSearch`**. Shared **`pixi.toml`**, **`Core/Sdk`**, and **`Agents/`** come from the same repo checkout — no nested clone or second lockfile.

## Commands

```bash
# From repo root (Pixi env; PYTHONPATH includes Tools/):
pixi run python -m WebSearch.cli --prompt "query" --route semantic
pixi run python -m WebSearch.doctor
pixi run python -m WebSearch.api
pixi run test-websearch

# Lint (scoped in root ruff.toml)
pixi run ruff check --config ruff.toml Tools/WebSearch
```

## Architecture

| Stage | Directory | Role |
|---|---|---|
| Frontend | `frontend/` | `dorks.py` (Google-dork builder), `websearchers.py` (provider registry + parallel fan-out), `hits.py` (normalize + near-dedupe) |
| Midend | `midend/` | `crawl_then_scrape()` — ordered crawler failover from `providers.yaml` |
| Backend | `backend/` | `prefilter.py`, `extractors.py`, `normalize.py`, `docs.py`, `store.py` (SQLite + vector index), `route.py` (fan-out to sql/semantic) |

**Library entry points** (lazy-loaded via `int_.py`):
- `run_pipeline(query, ...)` — search → crawl → extract (one call)
- `search_brief(query)` / `search_hits(query)` — agent-facing (`agent_tools.py`)
- `websearch_langchain_tools()` — LangChain integration (`langchain_tools.py`)

## Key gotchas

- **One package, one environment** — `WebSearch/` is a normal directory of this repo (no nested checkout, no second venv). Dependencies come from `Swarm/pyproject.toml` under the `websearch` extra: `uv sync --extra websearch` from the repo root.
- **`providers.yaml` is the source of truth** for searcher registry, crawler order, extractor order, dork presets, and LLM model rosters. Env var **names** only — never secret values. `$WEBSEARCH_PROVIDERS` overrides the path.
- **`swarm_sdk` dependency** — `websearchers.py` imports `swarm_sdk.retrieval.redis_exact`. Full features need the Swarm monorepo on `PYTHONPATH` or installed via uv.
- **Tests are fully offline** — fake backends, fake fetch. `test_toolcalling.py` covers tool-calling (OpenAI/Anthropic manifest shapes, dispatch). No conftest.py needed.
- **Crawler failover** — `crawlers.order` in YAML is tried sequentially; missing extras (e.g. `playwright`, `crawlee`) fail closed. `httpx2`/`requests`/`aiohttp` intentionally excluded from default order (plain HTTP, add latency on dead URLs).
- **Prefilter runs before extraction** — `backend/prefilter.py` enforces `schemes`, `blocked_domains`, `min_snippet_chars`, `require_title` from the YAML `prefilter:` block.
- **Google dorks** — `dork()` builds query strings; `parse_dork()` is its inverse. Providers with `dork: translate` map operators to API fields (Tavily, Exa, Parallel); others get raw text.
- **LLM models** — `claude-cli:default` and `codex-cli:default` use CLI login (no API key). `llm.model` is `provider:name` format. `WEBSEARCH_LLM_MODEL` overrides.
- **`--autonomous`** uses a model roster per role (playwright → dedupe → summarize); first ready model per role wins. `--doctor` shows readiness without printing keys.

## Config env vars

| Var | Effect |
|---|---|
| `WEBSEARCH_PROVIDERS` | Override providers file path |
| `WEBSEARCH_LLM_MODEL` | Override `llm.model` |
| `WEBSEARCH_EMBED_MODEL` / `WEBSEARCH_EMBED_DIM` | FastEmbed model/dimension |
| `WEBSEARCH_EMBED_BACKEND` | `lexical`, `fastembed`, or `llama-cpp` |
