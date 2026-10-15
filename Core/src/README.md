# Langswarm

A Python 3.15 multi-agent SDK built on LangChain 1.x, `langgraph-swarm`, and
LangSmith. Agents are declared in `config/swarm.yaml`; local retrieval,
dataset tools, deterministic SVG rendering, and the benchmark harness are
usable without an LLM call. Chat and provider-backed tools require credentials.

## Install and run

```bash
uv sync
cp .env.example .env
# Set OPENAI_API_KEY (or another configured provider key) in the ignored .env.
uv run langswarm
```

The first dependency installation needs package access. The first embedding
model use may download model files; after they are cached, the local FAISS
path can run without a network connection. LLM calls, live search, hosted
memory, and remote databases remain network operations.

## Features

- Thirteen YAML-configured agents with explicit handoff permissions.
- Provider registry for first-party LangChain integrations and
  OpenAI-compatible endpoints. `uv run langswarm --providers` reports
  whether each SDK and environment variable is present without printing keys.
- Local FAISS RAG with fastembed, optional local Qwen ONNX embeddings, and
  optional Postgres/pgvector, Prisma Postgres, or Supabase backends.
- Offline tools for notes, dataset inspection, validation, exact math,
  numerical calculations, serialization, and deterministic pixel art.
- Optional Redis/SQLite checkpointers, Mem0 long-term memory, read-only SQL,
  multi-engine search, DeepWiki, MCP, and gRPC integrations.
- FastAPI chat and SSE routes; LangSmith and OpenTelemetry instrumentation.

## Optional extras

```bash
uv sync --extra providers --extra websearch
uv sync --extra mem0 --extra redis
uv sync --extra postgres --extra supabase
uv sync --extra openvino --extra render --extra rpc
```

Only install extras used by this deployment. Set API keys in `.env`; do not
put credentials in YAML or source files.

## Useful commands

```bash
uv run langswarm --providers
uv run langswarm --bench
uv run langswarm-api
uv run python examples/ingest.py
uv run python examples/pixel_art.py
uv run pytest
uv run ruff check .
uv run ty check src tests examples
```

`uv run langswarm --bench` runs local checks. A benchmark using the embedding
model can require the model cache; a full conversational benchmark makes real
provider calls and is intentionally separate.

## API

- `GET /health`
- `GET /agents`
- `POST /chat` with `{"message":"...","thread_id":"..."}`
- `POST /chat/stream` with `{"message":"...","thread_id":"..."}` (server-sent events)

The API binds to `127.0.0.1` by default. Change `LANGSWARM_API_HOST` only when
you intend to expose it on another interface.

## Pixel scenes

`examples/pixel_scene.json` is a deterministic scene input. Render it with:

```bash
uv run python examples/pixel_art.py
```

SVG output uses the standard library and NumPy. PNG export requires the
`render` extra. Scenes use a fixed seed and bounded canvas dimensions.

## Layout

```text
langswarm/
├── config/swarm.yaml
├── examples/
├── src/langswarm/
├── tests/
├── .env.example
└── pyproject.toml
```
