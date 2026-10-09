# AGENTS.md — WebSearch

## All branches in the left sidebar (Cursor)

Open a **multi-root workspace**: **File → Open Workspace from File…** → [`All-Branches.code-workspace`](../All-Branches.code-workspace). For **git per lane**, use **GitKraken MCP** (`git_worktree` on `~/Myworkspace/Swarm`, `git_status` on each worktree path) or GitKraken **Worktrees** — see `~/Myworkspace/AGENTS.md`.

3-stage search pipeline: **frontend** (search providers) → **midend** (crawl/scrape) → **backend** (extract/normalize/store). Python package `WebSearch/` — the websearch feature the swarm agents call, part of the LangGraph Swarm SDK monorepo. See the parent `Swarm/AGENTS.md` for branch rules, quality gate, and security.

## Commands

```bash
# From the repository root (one uv environment, one pyproject.toml):
uv run --extra websearch websearch --prompt "query" --route semantic   # CLI: search → dedupe → summarize
uv run --extra websearch websearch --doctor                           # health: crawlers, providers, model readiness
uv run --extra websearch python -m WebSearch.api                      # FastAPI on 127.0.0.1:8765
uv run agents                                                         # validate Agents/*/agent.yaml

# Tests (offline — fake backends, no network, no API keys)
uv run pytest WebSearch/tests -q

# Lint
uv run ruff check WebSearch

# Optional error monitoring (requires secrets in Keychain / .env)
uv sync --extra observability
# SENTRY_DSN + SENTRY_ENVIRONMENT → WebSearch.api auto-inits via observability_sentry.py
```

## Sentry (MCP + SDK)

| Layer | Config | Auth |
| --- | --- | --- |
| **Cursor MCP** | Global server **`Sentry`** → `~/.gemini/mcp/sentry` | `SENTRY_ACCESS_TOKEN` (Keychain: `swarm/SENTRY_ACCESS_TOKEN`) |
| **This worktree** | [`Main/config/sentry.yaml`](../Main/config/sentry.yaml) | `SENTRY_ORG`, `SENTRY_PROJECT`, `SENTRY_REGION_URL` (slugs/URLs only) |
| **Runtime SDK** | `WebSearch/observability_sentry.py` | `SENTRY_DSN` — set with `uv run swarm-vault set SENTRY_DSN` |

In Agent chat, use Sentry MCP (`find_organizations`, `search_issues`, `analyze_issue_with_seer`) with org/project from env or `sentry.yaml` defaults. Prefer **GitKraken** for git; **Sentry MCP** for production errors affecting WebSearch.

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
