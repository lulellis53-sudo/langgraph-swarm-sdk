# LangGraph Swarm SDK

Parallel multi-LLM swarm on [LangGraph Swarm](https://github.com/langchain-ai/langgraph-swarm-py): specialist handoffs, asyncio fan-out, int8 memory, a cross-encoder reranker, a tokenizer budget, and a semantic cache. The point of the cache, reranker, and budget is to send fewer tokens and keep the tokens that remain relevant.

## Requirements

- Python `>=3.14.5` (`uv python install 3.14.5`)
- [uv](https://docs.astral.sh/uv/)

```bash
uv sync --extra dev --extra faiss --extra qdrant
```

FastEmbed is the default embedder and reranker. Current `onnxruntime` wheels do not include macOS x86_64, so that extra is skipped on Intel Macs. Tests inject a local embedder and do not download models.

## Run

```bash
uv run swarm-api
uv run swarm-grpc
```

`POST /v1/runs` with `{"text": "...", "thread_id": "t1"}`. `GET /v1/health`. gRPC `SwarmService.Run` and `SwarmService.Recall` call the same core.

Models come from `SWARM_ROUTER_MODEL` and `SWARM_SPECIALIST_MODEL` (LangChain `init_chat_model` ids). The router is the smaller model. Specialists run only after a cache miss.

## Token path

1. Exact SHA-256 cache, then a cosine semantic cache (default threshold `0.97`).
2. Tokenizer budget: stable system prompt first, then memories, then the newest turns. Tool text is capped.
3. sqlite-vec recall on int8 vectors (`BAAI/bge-small-en-v1.5`, 384-d, FastEmbed ONNX int8). FAISS and Qdrant are optional backends.
4. FastEmbed cross-encoder rerank (`Xenova/ms-marco-MiniLM-L-6-v2`); only top-k chunks are injected.
5. Near-duplicate memories are dropped with NumPy before the prompt.
6. Independent tasks fan out with `asyncio.gather` and `concurrent.futures`. Each specialist sees only its task. Handoffs inside the swarm use LangGraph. Parallel results are merged as short Pydantic JSON, not full transcripts.

HTTP peers use `httpx2` with HTTP/2 (`h2`). `aiohttp` and `requests` are the other clients.

## Checks

```bash
uv run --extra dev pytest
uv run --extra dev ruff check src tests
uv run --extra dev ty check src tests
```
