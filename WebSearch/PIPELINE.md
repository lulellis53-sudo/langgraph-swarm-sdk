# WebSearch pipeline

Entry point for the search/scrape/extract workflow in the Hatch package
`WebSearch/` (`packages = ["src/swarm_sdk", "WebSearch"]` in `pyproject.toml`).
Stages live at `WebSearch/frontend/`, `WebSearch/midend/`, and `WebSearch/backend/`
(plain data types between them):

```
  query
    │
┌───▼────────────────────────────────────────────────────────────┐
│ STAGE 1 · FRONTEND — search                                    │
│   frontend/dorks.py         Google-dork builder                │
│   frontend/websearchers.py  provider registry + parallel search │
│   frontend/hits.py          normalize + near-dedupe hits        │
│   → list[SearchHit]                                            │
├────────────────────────────────────────────────────────────┤
│ STAGE 2 · MIDEND — crawl/render                                │
│   midend/__init__.py        ordered_fetch, crawl_then_scrape   │
│   crawler order from providers.yaml (crawler: block)           │
│   → ScrapedPage (html bytes + url + crawler name)              │
├────────────────────────────────────────────────────────────┤
│ STAGE 3 · BACKEND — extract, normalize, store                  │
│   backend/prefilter.py      scheme/domain/title/snippet filter  │
│   backend/extractors.py     selectolax / trafilatura / bs4     │
│   backend/normalize.py      unicode + whitespace + URL canonicalizer │
│   backend/docs.py           ExtractedDoc + URL/blake2b/SimHash dedupe │
│   backend/store.py          SQLite documents table (WAL)       │
│   → ExtractedDoc rows in SQLite                                │
└────────────────────────────────────────────────────────────┘
```

## Entry points

| Surface | Use | Where |
| --- | --- | --- |
| `run_pipeline(query, ...)` | One call: search → crawl → extract | `__init__.py` |
| `search_brief(query)` | Search results as a numbered prompt brief | `agent_tools.py` |
| `search_hits(query)` | Structured hits (title, url, snippet, searcher_id) | `agent_tools.py` |
| `websearch_langchain_tools()` | `web_search_brief` / `web_search_hits` as LangChain tools | `langchain_tools.py` |
| `websearch --prompt Q [--site ...] [--route sql,semantic] [--forecast]` | CLI: one query to every provider (optional Google dork), dedupe/normalize, route to SQL and/or semantic summary+score, forecast hit volume | `cli.py` (`python -m WebSearch`) |
| `route(docs, targets, handlers)` | Normalize + dedupe once, fan out to `sql` (Persister) / `semantic` (Summarizer) | `backend/route.py` |
| `forecast_hits(conn, query)` | Daily hit-count forecast from recorded runs via `Prediction.ForecastEngine` (needs `PYTHONPATH` to the Swarm root + `--extra forecast`) | `forecast.py` |
| `websearch --browse [--model provider:name]` | An LLM searches and reads pages with Playwright, answers with citations; budgets from `llm:`; non-public URLs refused | `browse_agent.py` |
| `websearch --autonomous [--model provider:name]` | First Keychain-ready `autonomous.playwright` model browses; a different `autonomous.dedupe` model drops near-duplicates after blake2b | `autonomous.py` |
| `websearch --doctor` | Which crawlers, extractors, providers, Chromium and model are usable (read-only) | `doctor.py` |
| `python -m WebSearch.api` | FastAPI on `127.0.0.1:8765`: `/health`, `/doctor`, `/presets`, `/search`, `/browse` | `api.py` |
| `run_cowork_pipeline(urls)` | Deterministic 3-agent wave pipeline (LangGraph Pattern C): WebFetch → Normalizer → Persister | `cowork_agents.py` |
| `run_cowork_pipeline(..., fetch=...)` | Test override for GET (no Playwright needed) | `cowork_agents.py` |

## Persona contracts

The three deterministic agents are documented in the main repo's
`Agents/{WebFetch,Normalizer,Persister}/AGENTS.md` (persona, multipath
workflow, safety, checklists). `Agents/{Playwright,DedupeRouter,Summarizer}/AGENTS.md`
describe the browser-render, dedupe+route and summarize+score agents used by `websearch`. The crawler and `--route` paths make no LLM calls; heavy payloads
travel in the factory-bound scratchpad, never through the graph transcript. `websearch --autonomous` assigns a Keychain-ready chat model to Playwright and a different one to dedupe.

## Configuration

`providers.yaml` — searcher registry (api/env names, priorities), crawler
order, and the prefilter block (schemes, blocked_domains, min_snippet_chars,
require_title; values are normalized on load). See
`backend/prefilter.py::prefilter_hits` for the enforcement rules.

## Layout note

This file lives in the **`WebSearch/`** Python package. Sibling paths are
`frontend/`, `midend/`, `backend/`, and `providers.yaml`.

## Providers file: YAML or JSON

`load_providers()` reads `$WEBSEARCH_PROVIDERS`, else `providers.yaml`, else `providers.json`
(chosen by suffix; `websearch --providers FILE` overrides per run). Same schema either way:

| Block | Purpose |
| --- | --- |
| `searchers[].dork` | `native` sends a dork as typed (Google-style engines); `translate` maps operators to API fields (Tavily, Exa) |
| `crawlers.order` | Crawler failover order. Supported: `httpx`, `httpx2`, `requests`, `aiohttp`, `curl_cffi` (Chrome TLS fingerprint), `scrapy`, `playwright`, `crawlee`. `httpx2`/`requests`/`aiohttp` are off by default: they are plain HTTP clients and only add latency on dead URLs |
| `dork_presets` | Named dork options for `--preset`; `after_days`/`before_days` are relative to today |
| `llm` | `model` (`provider:name`, `WEBSEARCH_LLM_MODEL` overrides), `max_steps`, `max_pages`, `max_chars` |
| `autonomous` | `playwright` and `dedupe` lists of `provider:name`. A run uses the first name in each list whose registry key is in the environment or the macOS Keychain, and it will not give both roles to the same model. `WEBSEARCH_LLM_MODEL` does not change these lists |

## Google dorks

`frontend.dorks.dork()` builds `(a|b) AND "exact phrase" site: -site: filetype: intitle: inurl:
intext: -term after:YYYY-MM-DD before:YYYY-MM-DD`; `parse_dork()` is its inverse. For `translate`
providers the verified API fields (Tavily docs: `include_domains`, `exclude_domains`,
`start_date`, `end_date`; Exa docs: `includeDomains`, `excludeDomains`, `startPublishedDate`,
`endPublishedDate`) replace the text operators, so `site:` and the dates actually filter results.
Other providers receive the dork text and may ignore operators they do not support.

## LLM browser agent

`browse()` gives a chat model `web_search` and `open_page` tools. Pages render in headless Chromium
(`fetch_playwright`) and are reduced to main text with `trafilatura` first (menus and footers
dropped). The agent is limited by the `llm:` budgets, opens only public `http(s)` hosts (localhost,
private ranges and link-local addresses are refused), and is told to treat page text as data. The
check is on the URL the model picks and again on the URL the browser lands on, so a redirect onto a private address is refused.

`websearch --autonomous` uses that browser with the first ready name in `autonomous.playwright`
(Gemini, Kimi, Z.ai, MiniMax, Groq 120B, Cohere Command A, OpenRouter, then Mistral Large).
Opened HTML is extracted and exact copies are removed with blake2b. If two or more pages remain,
the first ready name in `autonomous.dedupe` (Cohere Command R7B, Groq 20B, the second Gemini and
Kimi keys, MiMo token plan, Ministral, SambaNova, then Fireworks) sees excerpts as data and
returns `{"keep": ["url", ...]}`. That name is never the Playwright model. A reply that is not
that JSON leaves the blake2b list in place. `autonomous.decision` is Jev: it chooses among
the ready Playwright names (the local classifier when `JEV_ENDPOINT` is unset). `autonomous.memory`
is Mem0: a brief for the same query from the last day is returned as-is, and a new answer is stored.
`websearch --doctor` prints each roster name as ready or not-ready and the selected names. It does
not print key values.

## OpenCLI notes (jackwener/opencli)

Read from its README on 2026-10-03. It is a Node/TypeScript tool (`npm i -g @jackwener/opencli`)
that turns websites into CLI commands through per-site adapters and drives the user's logged-in
Chrome through a browser-bridge extension plus a local daemon; it ships agent skills and a
`doctor` command. It is not a Python library, so it is not a dependency here. Ideas taken:
`doctor` (`websearch --doctor`), named reusable commands (`--preset`), and a small fixed set of
browser primitives for agents (`web_search`, `open_page`). Not taken: reusing the user's logged-in
browser session, which would hand an LLM-chosen URL the user's cookies.

## Agent models without an API key, OpenRouter web search, encrypted `.env`

- `claude-cli:default` runs `claude -p` and `codex-cli:default` runs `codex exec` (`codex-cli:profile:NAME`
  is `codex -p NAME`) on each CLI's own login, so no API key or balance is needed. Tools go through a
  JSON protocol (`swarm_sdk/models/cli_chat.py`); the child process runs in an empty temp dir, with the
  prompt on stdin and `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN` and `OPENAI_API_KEY` removed from its
  environment. Set `llm.model` (or `--model`) to use one. Codex returns a usage-limit error until its
  window resets.
- `openrouter_web` is a searcher: a cheap OpenRouter model runs the web-search plugin and the cited pages
  become hits. `site:`/`-site:` map to the plugin's `include_domains`/`exclude_domains`.
- `swarm-vault dotenv-set NAME [FILE]` prompts for a value (hidden, never in argv) and writes
  `NAME=enc:v1:<token>` to `FILE` (default `./.env`, mode 0600). The Fernet key lives only in the Keychain
  item `swarm/DOTENV_FERNET_KEY`, created on first use. Encrypted lines protect an `.env` that leaks by
  itself (backup, commit, copy); a process running as you with Keychain access can still decrypt it.
  `swarm_sdk.vault.get` decrypts on demand (source `dotenv-encrypted`) and `swarm_sdk.config.settings`
  does not export `enc:v1:` lines to the environment.

## Added for structured extraction and testing

- `langextract` (google/langextract 1.7.0) is in the `websearch` extra for pulling structured fields (entities,
  dates, claims) out of scraped page text with an LLM. It is installed and imports; no pipeline stage calls it yet.
- OpenCLI (`@jackwener/opencli`) was only tried, not added: installed with `--ignore-scripts` into a scratch dir
  (its `postinstall` writes shell completions and downloads adapters into `~/.opencli`). `hackernews top` works with
  no browser; browser commands need its Chrome extension, which is not installed. Its daemon (127.0.0.1:19825) was
  stopped and `~/.opencli` removed afterwards.

