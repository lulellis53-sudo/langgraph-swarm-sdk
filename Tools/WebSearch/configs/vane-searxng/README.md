# Vane + SearXNG without Docker

Configs and steps to run [Vane](https://github.com/ItzCrazyKns/Vane)
(ex-Perplexica, MIT) and its SearXNG backend directly with Node.js and Python —
no containers — and wire them into WebSearch's `searxng` searcher.

Integration compatibility stamp: **0.3.0** (2026-10-13). Upstream Vane tags
are `v1.x` — there is no `v0.3.0` release; the stamp versions this vendored
config against upstream `master`.

## 1. SearXNG (Python, no Docker)

```bash
git clone https://github.com/searxng/searxng.git
cd searxng
./manage pyenv    # create the virtualenv and install
SEARXNG_SECRET="$(openssl rand -hex 32)" \
SEARXNG_SETTINGS_PATH="$PWD/settings-websearch.yml" \
./manage start    # serves http://127.0.0.1:8888 by default
```

Copy [`settings.yml`](settings.yml) to `settings-websearch.yml` first. The
instance must list `json` under `search.formats` — both Vane and WebSearch call
the JSON API (`/search?q=...&format=json`).

## 2. Vane (Node.js, no Docker)

```bash
git clone https://github.com/ItzCrazyKns/Vane.git
cd Vane
npm i
npm run build
npm run start     # http://localhost:3000
```

In the setup screen point Vane at the local SearXNG URL
(`http://127.0.0.1:8888`) and configure your LLM provider.

## 3. WebSearch integration

```bash
export SEARXNG_URL=http://127.0.0.1:8888
uv run --extra websearch websearch --prompt "langgraph handoffs" --route semantic
```

With `SEARXNG_URL` set, the keyless `searxng` searcher in
[`providers.yaml`](../../providers.yaml) joins the parallel fan-out; without it
it fails closed with status `no_key`.

Browser-level smoke tests live in
[`tests/test_vane_playwright.py`](../../tests/test_vane_playwright.py)
(`uv sync --extra scraping && playwright install chromium`, then set
`SEARXNG_URL` / `VANE_URL`).

## References (official docs)

- Vane README, non-Docker installation:
  <https://github.com/ItzCrazyKns/Vane#non-docker-installation>
- Vane Search API (`POST /api/search`, `GET /api/providers`):
  <https://github.com/ItzCrazyKns/Vane/blob/master/docs/API/SEARCH.md>
- SearXNG Search API (`GET /search`, `format=json`):
  <https://docs.searxng.org/dev/search_api.html>
- SearXNG `settings.yml` reference:
  <https://docs.searxng.org/admin/settings/index.html>
