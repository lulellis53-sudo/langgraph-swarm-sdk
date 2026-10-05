# WebSearch workflow

This page points to the standalone WebSearch worktree. Its maintained
architecture, commands, configuration, and security notes are in the
[WebSearch pipeline guide](../WebSearch/PIPELINE.md) and
[WebSearch README](../WebSearch/README.md). Use those files as the source of truth;
this summary is intentionally short to avoid duplicating the implementation
guide.

## Pipeline at a glance

```text
query
  → frontend: configured providers search in parallel and normalize results
  → midend: configured crawlers fetch or render selected URLs
  → backend: prefilter, extract, normalize, deduplicate, and persist documents
```

The stages exchange structured data. Search-only callers can use the hit and
brief helpers; ingestion callers can use the full pipeline. Exact entry points
and configuration fields are documented in [`WebSearch/PIPELINE.md`](../WebSearch/PIPELINE.md).

## Development

Work from the WebSearch worktree and use its own `uv.lock` and virtual
environment. The canonical setup, test, lint, and type-check commands are in
[`WebSearch/README.md`](../WebSearch/README.md). Inject search/fetch clients in
tests to keep them deterministic and offline.
