# LangGraph Swarm SDK

Parallel multi-LLM swarm on [LangGraph Swarm](https://github.com/langchain-ai/langgraph-swarm-py): specialist handoffs, asyncio fan-out, int8 memory, a cross-encoder reranker, a tokenizer budget, and a semantic cache. The point of the cache, reranker, and budget is to send fewer tokens and keep the tokens that remain relevant.

## Requirements

- Python `>=3.14.5` (`uv python install 3.14.5`)
- [uv](https://docs.astral.sh/uv/)

```bash
uv sync --extra dev --extra faiss --extra qdrant
```

Optional **Jupyter Notebook + Jupyter AI** (uses prebuilt `cryptography` wheels; see `[tool.uv]` in `pyproject.toml`):

```bash
uv sync --extra jupyter --extra dev
uv run python -m ipykernel install --user --name=swarm --display-name="Python (Swarm)"
uv run jupyter lab    # or: uv run jupyter notebook
```

FastEmbed is the default embedder and reranker. Current `onnxruntime` wheels do not include macOS x86_64, so that extra is skipped on Intel Macs. Tests inject a local embedder and do not download models.

## Run

```bash
uv run swarm-api
uv run swarm-grpc
```

`POST /v1/runs` with `{"text": "...", "thread_id": "t1"}`. `GET /v1/health`. gRPC `SwarmService.Run` and `SwarmService.Recall` call the same core.

Predefined providers and routes live in [`config/swarm.yaml`](config/swarm.yaml). Per-agent roles, models, and tasks live in [`Agents/{Name}/agent.yaml`](Agents/Tester/agent.yaml) (see [`Agents/SKILLS.md`](Agents/SKILLS.md)). `SWARM_*` env vars override file defaults. Open [`codeworkspace/swarm.code-workspace`](codeworkspace/swarm.code-workspace) for a multi-root editor layout.

## Token path

1. Exact SHA-256 cache, then a cosine semantic cache (default threshold `0.97`).
2. Router on `think_level: low` with provider fallback and circuit breakers (`GET /v1/health` shows breaker state).
3. Think-level token caps, then tokenizer budget (system prompt, memories, newest turns; tool text capped).
4. Hybrid dense + BM25 recall (RRF), dedupe, rerank; only top-k snippets injected. sqlite-vec int8 + optional FTS5 side index.
5. Near-duplicate memories dropped before the prompt.
6. Parallel fan-out with bounded concurrency and JSON briefs; LangGraph handoffs for sequential specialist work.

HTTP peers use `httpx2` with HTTP/2 (`h2`). `aiohttp` and `requests` are the other clients.

## Checks

```bash
uv run --extra dev pytest tests benchmark -q
uv run --extra dev ruff check src tests benchmark
uv run --extra dev ty check src tests benchmark
uv run python -m swarm_sdk.agents.validate
```
