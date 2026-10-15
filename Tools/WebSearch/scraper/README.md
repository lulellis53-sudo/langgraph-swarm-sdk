# WebSearcherMCP

Self-contained MCP server (stdio) for web search and scraping. It imports nothing from the other
lanes (`WebSearch`, `swarm_sdk`, ...).

## Tools

| Tool | Backend | Needs |
| --- | --- | --- |
| `searxng_web_search` | local SearXNG; hits are canonicalized, deduped, query-pruned, and packed into `max_tokens` | `SEARXNG_URL` (default `http://127.0.0.1:8888`) |
| `crawl4ai_scrape` | local Crawl4AI | Keychain `CRAWL4AI_API_TOKEN`; `CRAWL4AI_URL` (default `http://127.0.0.1:11235`) |
| `google_search_agent` | Gemini Google Search grounding; returns the answer plus cited sources; optional `since`/`until` (RFC 3339, together) | `GOOGLE_API_KEY` (+ `_1`, `_2` fallbacks); billing enabled (search grounding answers 429 on the free tier) |
| `perplexica_search` | local Perplexica: web search through our SearXNG plus a cited answer (about 1 minute); the ids in `config.env` select Perplexica's own "Token Harbor" provider (free `deepseek-v4.1-flash:free`) and its local embeddings | `PERPLEXICA_URL`, `PERPLEXICA_CHAT_*`, `PERPLEXICA_EMBED_*` (set in `config.env`) |
| `deep_search` | SearXNG, then Crawl4AI on the top URLs. Google is opt-in (`use_google=true`) because Gemini Google Search is billed per search | SearXNG and Crawl4AI |
| `scrape_and_ingest` | Crawl4AI, then chunk (polars), embed (FastEmbed, int8 MiniLM) and store in Postgres/pgvector; re-ingesting a URL replaces its chunks | Keychain `WEBSCRAPER_PG_PASSWORD` |
| `semantic_search` | pgvector cosine search plus query-term rerank; snippets packed into `max_tokens` | same |
| `ask_with_sources` | stored chunks and SearXNG results, answered by the helper LLM with `[n]` citations | same, plus any LLM key below |
| `warmup` | loads the embedding model (and its chunking tokenizer) now, so the first search or ingest is fast; `include_english_int8` also starts `all-MiniLM-L6-v2-int8`. Set `WEBSCRAPER_WARMUP=1` in `config.env` to do it at every server start | none |
| `health_check` | state of every backend; `probe_llm` sends one 5-token request per helper-LLM key | none |
| `x_search` | xAI Grok `x_search` tool (Responses API, `grok-4.7`): searches X posts with citations; optional handle filters and a date range. Opt-in and billed by xAI per search; no other tool calls it | Keychain `XAI_API_KEY` on an account with credits (it answers 403 while the account has none) |
| `llm_ask` | helper LLM from `providers.yaml`: the first enabled provider that answers. Gemini is listed but disabled | the provider keys in the Keychain |

## Layout

```
WebScraper/
  websearcher_mcp.py   the server (tools above)
  __main__.py          python -m WebScraper
  scripts/             websearcher (launcher), compose (docker compose with Keychain secrets), sync-secrets (1Password -> Keychain)
  config.env           non-secret settings (URLs, model names, LLM_FIRST)
  searxng/             compose.yaml + settings.yml + limiter.toml (secret in SEARXNG_SECRET)
  tests/               MCP, tokensaver, hits, LangChain bindings
  semantic.py          FastEmbed + pgvector store + polars chunking/rerank
  hits.py              URL canonicalize, snippet prune, lexical score
  tokensaver.py        greedy pack into a token budget (near-dup + min_score)
  agent_tools.py       compact search/semantic helpers for agents
  langchain_tools.py   `webscraper_langchain_tools()` for LangChain/LangGraph
  llm.py               helper-LLM client: reads providers.yaml, retries, falls through
  providers.yaml       the helper-LLM chain: provider, model, effort, maxretry, maxms, enabled
  pgvector/            compose.yaml for Postgres + pgvector (127.0.0.1:5433)
  crawl4ai/            compose.yaml for Crawl4AI (127.0.0.1:11235)
  pyproject.toml       own project and .venv (Python 3.12, see below)
  pipeline.py, text_processors.py, api.py   older DuckDB pipeline and HTTP API (not used by the MCP tools)
```

## Environment

The server has its own project (`WebScraper/pyproject.toml`, Python 3.12) and its own `.venv`. FastEmbed needs
`onnxruntime`, which has no wheels for Python 3.14 or for Intel macOS in recent releases, so the repo-wide
3.14 environment cannot run it. `onnxruntime` is pinned below 1.24 for the same reason.

```sh
uv sync --project WebScraper --python 3.12
uv sync --project WebScraper --python 3.12 --group dev   # pytest + LangChain tools
```

### LangChain / LangGraph

```python
from langchain.agents import create_agent
from WebScraper.langchain_tools import webscraper_langchain_tools

tools = webscraper_langchain_tools()
agent = create_agent(model="openai:gpt-4.1-mini", tools=tools)
```

Bind on an existing model with ``model.bind_tools(webscraper_langchain_tools())``.
Pass ``fetch=`` / ``semantic=`` in tests so SearXNG and Postgres are not required.
Each search tool takes ``max_tokens`` and ``min_score`` so the agent can keep
prompt context small.

Embedding model: `WEBSCRAPER_EMBED_MODEL`, default `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
(int8 ONNX, 384 dims). `all-MiniLM-L6-v2-int8` selects the English-only int8 model (Xenova quantized file).
Chunking is token-aware: `semantic.chunk_by_tokens` packs sentences with the model's own tokenizer so that
every chunk fits the model's window (126 tokens plus the two special tokens for the default model, whose
tokenizer would otherwise cut the rest silently), with a 12% token overlap. Each chunk's real token count is
stored in `n_tokens`.
Changing the model does not mix vectors: each chunk is stored with its model and searched only against it.

## Run

```sh
WebScraper/scripts/compose searxng up -d      # SearXNG
WebScraper/scripts/compose pgvector up -d     # Postgres + pgvector
WebScraper/scripts/compose crawl4ai up -d     # Crawl4AI
WebScraper/scripts/websearcher          # stdio MCP server (what .mcp.json runs)
python -m WebScraper                    # same, with the environment already set
WebScraper/.venv/bin/python -m pytest -q WebScraper/tests   # from the repo root
```

## Helper-LLM providers

`providers.yaml` is the chain, in order. Per provider: `base_url`, `keys` (environment variable names; the
values come from the Keychain), `model`, `effort` (answer budget: low 300, medium 800, high 1500, xhigh 3000
output tokens), `maxretry` (extra attempts per key on 429, 5xx or a timeout; never on 401/402/403/404),
`maxms` (per-request timeout in milliseconds), `enabled` and an optional `extra_body` (fields merged into
every request). A top-level `defaults:` block fills what a
provider leaves out. Gemini is present with `enabled: false`; set it to `true` to bring it back.
`<NAME>_MODEL` overrides one model, `LLM_FIRST=<name>` moves a provider to the front, and
`WEBSCRAPER_PROVIDERS` points at another file. Quote a provider name that YAML would read as a boolean
(`on`, `off`, `yes`, `no`): the loader rejects those with a clear error.
Free providers that answered on 2026-10-09 (fastest first): Mistral `open-mistral-nemo`, Cohere
`command-r7b-12-2024` (trial key), NVIDIA `nemotron-3.5-lightning-30b-a3b` (thinking switched off through
`extra_body`), Ollama Cloud `gpt-oss:20b`, OpenRouter `nvidia/nemotron-3-ultra-550b-a55b:free`, Poolside
Laguna `poolside/laguna-s-2.1:free` (free on OpenRouter), Token Harbor `claude-haiku-5.5:free` (1.8 s; the live free list also has two DeepSeek and two MiMo models). Tested and excluded, with the reason, at the bottom of `providers.yaml`
(OpenCode Zen works only inside OpenCode; SambaNova, Chutes and Hugging Face answer 402). MiniMax, Kimi, Z.ai,
Claude (OAuth), Grok (OAuth) and MiMo are paid tiers and are not in the chain.
Paid providers (tried only after every free one failed): Kimi Code plan `kimi-for-coding` (`api.kimi.com/coding/v1`),
Fireworks `gpt-oss-120b`, Poolside's direct API
`laguna-s-2.1`, MiniMax `MiniMax-M3` (its `<think>` block is stripped). Two OAuth subscriptions run through the
official CLIs (`kind: cli`): Claude Code (`claude -p --safe-mode --tools ""`, on) and Codex (`codex exec -s read-only`,
**off**). A cli provider gets the prompt on stdin, runs in an empty temporary directory with a short allow-list of
environment variables (none of your API keys) and is killed at `maxms`; their OAuth tokens are never read.
`--safe-mode` matters: without it the child loaded your user-level MCP servers (1Password, GitKraken). Codex stays off
because its read-only sandbox still lets it read any file, and a canary test made it print one; enable it only for
prompts you trust. Listed but disabled, each with its reason: Z.ai's GLM Coding Plan (`api.z.ai/api/coding/paas/v4`, works, but its FAQ
allows plan calls only in supported tools), MiMo (401), Claude Sonnet 5.5 on Token Harbor (the first key, the one you
paid on, needs its email verified; the second has a $0 balance), Step Flash (paid), Gemini (avoided).
`google_search_agent` is separate: it is Gemini Google Search grounding, not part of this chain.

## Secrets

Secrets live in the macOS Keychain, service `swarm/<NAME>` (the same convention as `swarm_sdk.vault`). 1Password is
the source of truth (document `txt`). The launcher reads only the Keychain, so there is no 1Password prompt at every start,
and nothing in this folder reads a plaintext env file.

| Script | Does |
| --- | --- |
| `scripts/websearcher` | the MCP launcher: Keychain secrets, then `config.env` for non-secret settings |
| `scripts/compose <svc> ...` | `docker compose` for `searxng`, `pgvector` or `crawl4ai` with secrets from the Keychain |
| `scripts/sync-secrets` | 1Password to Keychain: reads the 1Password document `txt` (fallback `.env`, vault Personal; archived documents are read too). Default stores only missing secrets; `--check` lists names whose Keychain value differs (no changes); `--refresh` also overwrites differing ones, so use it after you rotate a key in 1Password |

Add or change one secret without echoing it: `uv run swarm-vault set TOKEN_HARBOR_API_KEY` (from the repo root).
The list of names the project uses is in `scripts/_secrets.zsh`. Existing environment variables win over the Keychain.

## Services

| Service | Where | Port |
| --- | --- | --- |
| SearXNG | `searxng/compose.yaml` (container `searxng`, bound to 127.0.0.1) | 8888 |
| Crawl4AI | `crawl4ai/compose.yaml` (container `crawl4ai`, bound to 127.0.0.1, `CRAWL4AI_API_TOKEN` required) | 11235 |
| Postgres + pgvector | `pgvector/compose.yaml` (container `webscraper-pgvector`, password in `WEBSCRAPER_PG_PASSWORD`) | 5433 |
| Perplexica | container `perplexica-vane-1` (not defined here); its search points at `host.docker.internal:8888` and its "Token Harbor" provider holds that key in Perplexica's own settings | 3000 |

Use `scripts/compose <service> <args>` for `up` and `down`: the compose files require their secrets, and the wrapper
loads them from the Keychain.
