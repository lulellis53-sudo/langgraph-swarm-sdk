# Websearch integration

`WebSearch/` is the canonical multiprovider implementation and configuration.
This directory is the stable `Tools/Websearch` entry point; `providers.yaml`
is a symlink to `../../WebSearch/providers.yaml`, so provider changes have one
source of truth.

## Search flow

```text
Query
  └─ parallel fan-out to enabled providers in providers.yaml
       ├─ provider-local failure isolation
       ├─ normalize URLs and deduplicate results
       ├─ rank provider agreement with reciprocal-rank fusion
       └─ optional crawl, extract, semantic route, or cited browse
```

The registry currently enables Brave, DuckDuckGo (package and Lite), Tavily,
OpenRouter Web, Parallel, Jina, Exa, Google Search, DuckDuckGo MCP, Context.dev,
and Bright Data. Context7 is listed as a documentation source. Apify and Kimi
Search are present but disabled. The doctor command reports which enabled
providers are ready without printing credential values.

## Use this directory's registry

```bash
uv run --extra websearch websearch \
  --providers Tools/Websearch/providers.yaml --doctor

uv run --extra websearch websearch \
  --providers Tools/Websearch/providers.yaml \
  --prompt "query" --route semantic
```

The same path can be selected for Python callers with
`WEBSEARCH_PROVIDERS=Tools/Websearch/providers.yaml`. Without an override,
the existing CLI and SDK continue to load `WebSearch/providers.yaml`.

Provider credentials are environment-variable names in the registry only.
Supply the corresponding values through the approved secret store or process
environment; never add credential values to either YAML path.

## Source files

- Provider registry: [`providers.yaml`](providers.yaml) → [`WebSearch/providers.yaml`](../../WebSearch/providers.yaml)
- Pipeline and CLI: [`WebSearch/README.md`](../../WebSearch/README.md)
- Provider loader: [`WebSearch/frontend/registry.py`](../../WebSearch/frontend/registry.py)
