# WebSearch

This directory is a **git worktree** of branch `worktree/websearch` (package files at the worktree root). From the SDK checkout:

```bash
git worktree add WebSearch worktree/websearch
```

Search/scrape pipeline. HTTP searchers fail closed (empty hits) without keys.

| Layer | Path | Role |
| ----- | ---- | ---- |
| Frontend | [`frontend/providers.py`](frontend/providers.py), [`frontend/apis.py`](frontend/apis.py), [`frontend/websearchers.py`](frontend/websearchers.py) | [`providers.yaml`](providers.yaml); Brave, Tavily, Apify, Exa, SearXNG (DDG+Bing) |
| Midend | [`midend.py`](midend.py) | Crawlers httpx → scrapy → playwright → crawlee (`http`/`https` only) |
| Backend | [`backend.py`](backend.py) | selectolax, selectolax_regex, regex, trafilatura, bs4 + normalize |
| Retry | [`repeater.py`](repeater.py) | `@repeater.s` on I/O (`TimeoutError` / `OSError` / `ConnectionError`) |

Env var **names** only in yaml (`BRAVE_API_KEY`, `TAVILY_API_KEY`, `APIFY_TOKEN`, `EXA_API_KEY`, `SEARXNG_URL`). Optional extra: `uv sync --extra websearch`. Inject `SearchFn` / `FetchFn` in tests so no live network is required.
