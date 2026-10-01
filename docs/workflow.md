# WebSearch workflow

End-to-end flow for this worktree: configure providers, run search, optionally scrape and extract.

## Pipeline

```text
providers.yaml
       │
       ▼
┌──────────────────┐     parallel (default) or ordered failover
│  frontend/       │     parallel_search / registry_search
│  search + fuse   │──── prefilter → RRF → URL dedupe → normalize → near-dedupe
└────────┬─────────┘
         │ SearchHit URLs
         ▼
┌──────────────────┐
│  midend/         │     httpx → scrapy → playwright → crawlee (yaml order)
│  crawl_then_scrape
└────────┬─────────┘
         │ HTML bytes
         ▼
┌──────────────────┐
│  backend/        │     extractors (yaml order) + normalize_text
│  extract docs    │
└──────────────────┘
```

`run_pipeline(query)` runs all three stages. Agents usually call `search_hits` / `search_brief` (`agent_tools.py`) for ranked hits only.

## Setup

```bash
cd /Users/usuario/Swarm-WebSearch
uv sync --extra dev
```

Interpreter: `.venv` (Python 3.14). Cursor is pointed at `${workspaceFolder}/.venv/bin/python`.

Export API keys referenced in `providers.yaml` (names only in yaml; values from the environment). Missing keys fail closed for that searcher.

Optional local SearXNG (DuckDuckGo + Bing):

```bash
# docker/.env with SEARXNG_SECRET=...
docker compose -f docker/compose.yaml up -d --build
export SEARXNG_URL=http://127.0.0.1:8888
```

## Daily commands

| Task                           | Command                                 |
| ------------------------------ | --------------------------------------- |
| Tests                          | `uv run pytest tests -q --tb=short`     |
| AST + lint + types             | `uv run python scripts/check_python.py` |
| Lint                           | `uv run ruff check .`                   |
| Types (ty)                     | `uv run ty check .`                     |
| Docstrings + annotations (AST) | `uv run python scripts/validate_ast.py` |
| Format check                   | `uv run ruff format --check .`          |
| Format apply                   | `uv run ruff format .`                  |
| Trunk (repo)                   | `trunk check` / `trunk fmt`             |

## Entry points

| Goal                      | API                                                     |
| ------------------------- | ------------------------------------------------------- |
| Ranked hits               | `from WebSearch import search_hits`                     |
| Prompt brief              | `from WebSearch import search_brief`                    |
| Full pipeline             | `from WebSearch import run_pipeline`                    |
| Google dork string        | `from WebSearch import dork` — see [dorks.md](dorks.md) |
| Design (prefilter/sink)   | [design-prefilter.md](design-prefilter.md)              |
| Future (TOML + liveboard) | [design-liveboard.md](design-liveboard.md)              |

## Configuration

- `providers.yaml` — searcher order, crawl limits, extractor/crawler order, `prefilter:` policy.
- Tests inject `SearchFn` / `FetchFn` so CI needs no live network.

## Layout

| Path             | Role                                                |
| ---------------- | --------------------------------------------------- |
| `frontend/`      | Registry, HTTP searchers, prefilter, fusion, dorks  |
| `midend/`        | Fetch/scrape hit URLs                               |
| `backend/`       | HTML → text, doc dedupe                             |
| `agent_tools.py` | Agent-facing `search_hits` / `search_brief`         |
| `repeater.py`    | URL normalization, I/O retries                      |
| `tests/`         | pytest (conftest registers `WebSearch` import path) |
| `docker/`        | Optional SearXNG image                              |
