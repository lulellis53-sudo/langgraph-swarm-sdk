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

FastEmbed is the default embedder and reranker. Its default model (`sentence-transformers/all-MiniLM-L6-v2`, MiniLM2) is ONNX INT8 on CPU. Token budgets use **tiktoken** (`cl100k_base`) by default, with optional Hugging Face `tokenizers.Tokenizer` packing. sqlite-vec stores int8 vectors; Qdrant can use scalar int8 when `vectorstore.quantization` is `int8`. FAISS GPU (`vectorstore.gpu: true`) needs a CUDA `faiss-gpu` build and falls back to CPU when that is missing.

### GPU acceleration on Intel Mac + AMD Radeon Pro 5300M

Swarm can now use **MoltenVK/Vulkan** for embeddings and **OpenCL** for vector math / search on a 2019 Intel Mac:

- `LlamaCppEmbedder` runs a GGUF embedding model through `llama-cpp-python` with Vulkan/MoltenVK.
- `OpenClVecStore` is a brute-force vector store that offloads inner-product search to the GPU.
- The shared `swarm_sdk.gpu` dispatcher accelerates batch cosine/dot/norm for dedupe and the semantic cache.

Install the optional extras and build `llama-cpp-python` with Vulkan:

```bash
uv sync --extra dev --extra opencl --extra llama-cpp
CMAKE_ARGS='-DGGML_VULKAN=on' uv pip install --no-build-isolation llama-cpp-python
```

Configure in `src/swarm_sdk/agents/config/swarm.yaml` (or via `SWARM_*` env vars):

```yaml
embedding:
  backend: llama-cpp
  llama_model: /path/to/bge-small-en-v1.5-q4_0.gguf

vectorstore:
  backend: opencl
  opencl_enabled: true
```

Inspect the host map and selected backends with:

```bash
uv run python -m swarm_sdk.accel
```

Current `onnxruntime` wheels do not include macOS x86_64, so FastEmbed is skipped on Intel Macs unless ORT is installed another way. Tests inject a local embedder and do not download models.

## Run

```bash
uv run swarm-api
uv run swarm-grpc
```

`POST /v1/runs` with `{"text": "...", "thread_id": "t1"}`. `GET /v1/health`. gRPC `SwarmService.Run` and `SwarmService.Recall` call the same core.

## Orchestration engine

`swarm_sdk.orchestrator` runs a goal as a parallel multi-agent plan:

1. `spawn(goal, manifests)` — the Orchestrator agent decomposes the goal into a JSON plan (validated by pydantic; falls back to a single-step plan on malformed output).
2. `run_plan(plan, factory)` — a LangGraph `StateGraph` executes the plan in dependency waves; steps in the same wave run concurrently via `asyncio.gather` (uvloop; the runtime thread pool widens automatically on free-threaded Python 3.14).
3. Each step is a `WorkerAgent` bound to its `Agents/{Name}/agent.yaml` manifest: model, `think_level`, `effort`, and `token_budget` are pre-selected per agent; the system prompt is the role contract from that agent's `AGENTS.md`; the step prompt carries only its declared `inputs` (dependency outputs), never the whole transcript.

Token savings: shared role-contract prompt cached per process, exact + semantic step cache (`SemanticCache`), hard `max_prompt` packing, and per-step usage totals (`prompt_tokens`, `completion_tokens`, `llm_calls`, `cached_calls`) reported in `PlanResult.usage`.

gRPC: `SwarmService.SpawnPlan` (goal → plan handle), `RunPlan` (handle → per-step outputs + usage), `PlanStatus` (poll for long plans). Manifests may set `api_key_env: SWARM_<NAME>_API_KEY` — the env var *name*, never the key value.

Predefined providers and routes live in [`src/swarm_sdk/agents/config/swarm.yaml`](src/swarm_sdk/agents/config/swarm.yaml). Per-agent roles, models, and tasks live in [`Agents/{Name}/agent.yaml`](Agents/Tester/agent.yaml) (see [`Agents/README.md`](Agents/README.md)). `SWARM_*` env vars override file defaults. Open [`codeworkspace/swarm.code-workspace`](codeworkspace/swarm.code-workspace) for a multi-root editor layout.

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
