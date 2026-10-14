# Langswarm

A twelve-agent swarm on LangGraph + LangSmith, defined in YAML, built end to
end first. The core install gives you the full swarm: local RAG (faiss-cpu +
fastembed), handoffs, a REPL, an HTTP API, and a benchmark suite — all
offline-capable except the LLM calls themselves.

## Quickstart (the guaranteed path)

    uv sync
    cp .env.example .env          # set OPENAI_API_KEY at minimum
    uv run langswarm              # interactive REPL over config/swarm.yaml
    uv run python examples/quickstart.py

## RAG

Fully local by default: fastembed embeds on CPU through onnxruntime, and
faiss-cpu keeps the index on disk. Switch to Postgres + pgvector for durable
multi-process deployments by setting `LANGSWARM_VECTOR_BACKEND=pgvector`.

    uv run python examples/ingest.py notes.txt   # add a document

## Serving

    uv run langswarm-api                          # FastAPI, SSE, uvloop
    curl -X POST localhost:8000/chat -H 'content-type: application/json' \
         -d '{"message":"hi","thread_id":"t1"}'

gRPC: generate stubs once (see the run book below), then `uv run python -m
langswarm.rpc`.

## Observability

Set `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY`; every agent, handoff,
and tool call appears in the LangSmith UI. `langswarm.telemetry` additionally
installs an OpenTelemetry TracerProvider for OTel-native backends.

## Quality gates

    uv run pytest
    uv run ruff check .
    uv run ty check src
    uv run lifeguard run-tree src --python-version 3.15

The last command statically verifies PEP 810 lazy-import safety of the whole
codebase with Meta's Lifeguard analyzer.

## Benchmarks

    uv run python -m langswarm.bench            # offline suite, rich report
    uv run python -m langswarm.bench --e2e     # adds one full swarm turn

## Lazy imports

Every module opts its heavy imports into PEP 810 lazy loading via
`__lazy_modules__`, and the package root resolves public names on first
access. For a process-wide lazy mode: `PYTHONLAZYIMPORTS=1 uv run langswarm`.
