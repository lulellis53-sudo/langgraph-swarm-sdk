# LangGraph Swarm SDK

Parallel multi-LLM swarm on [LangGraph Swarm](https://github.com/langchain-ai/langgraph-swarm-py): specialist handoffs, asyncio fan-out, int8 memory, a cross-encoder reranker, a tokenizer budget, and a semantic cache. The point of the cache, reranker, and budget is to send fewer tokens and keep the tokens that remain relevant.

## Requirements

- Python `>=3.14.7` (`uv python install 3.14.5`)
- [uv](https://docs.astral.sh/uv/)

```bash
uv sync --extra dev --extra faiss --extra qdrant --extra mem0
```

Optional **Jupyter Notebook + Jupyter AI** (uses prebuilt `cryptography` wheels; see `[tool.uv]` in `pyproject.toml`):

```bash
uv sync --extra jupyter --extra dev
uv run python -m ipykernel install --user --name=swarm --display-name="Python (Swarm)"
uv run jupyter lab    # or: uv run jupyter notebook
```

FastEmbed is the default embedder and reranker. Its default model (`sentence-transformers/all-MiniLM-L6-v2`, MiniLM2) is ONNX INT8 on CPU. Token budgets use **tiktoken** (`cl100k_base`) by default, with optional Hugging Face `tokenizers.Tokenizer` packing. sqlite-vec stores int8 vectors; Qdrant can use scalar int8 when `vectorstore.quantization` is `int8`. Set `vectorstore.backend: mem0` (optional extra `mem0`) to use [Mem0](https://docs.mem0.ai/) Platform `MemoryClient` for long-term recall (`MEM0_API_KEY`; env var *name* only in YAML). FAISS GPU (`vectorstore.gpu: true`) needs a CUDA `faiss-gpu` build and falls back to CPU when that is missing.

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

### Use with LangChain

From the Swarm checkout (LangGraph already depends on LangChain):

```python
from langchain.agents import create_agent
from WebSearch.langchain_tools import websearch_langchain_tools

tools = websearch_langchain_tools()
agent = create_agent("openai:gpt-4o-mini", tools=tools)
agent.invoke({"messages": [("user", "What changed in LangGraph swarm handoffs lately?")]})
```

Bind tools on an existing graph node with ``model.bind_tools(websearch_langchain_tools())``. Pass ``backends=`` when testing so no API keys are required (same injectable ``SearchFn`` as :func:`search_hits`).

**Pydantic AI:** wrap a single tool with ``pydantic_ai.ext.langchain.tool_from_langchain`` or attach a LangChain toolkit via ``LangChainToolset`` — see [Pydantic AI third-party tools](https://ai.pydantic.dev/toolsets/#langchain-tools). Swarm’s runtime stays on LangGraph; use Pydantic AI for standalone agents and bridge tools as needed.

Env var **names** only in yaml (`BRAVE_API_KEY`, `TAVILY_API_KEY`, `APIFY_TOKEN`, `EXA_API_KEY`, `SEARXNG_URL`). Install deps: `uv sync --extra dev`. Inject `SearchFn` / `FetchFn` in tests so no live network is required.

Mem0 Platform long-term memory (optional extra; does not replace the LangGraph checkpointer):

```yaml
vectorstore:
  backend: mem0
  mem0:
    api_key_env: MEM0_API_KEY
    user_id: swarm
    agent_id: swarm-sdk
    infer: false
```

API keys (`MEM0_API_KEY`, `TAVILY_API_KEY`, `BRAVE_API_KEY`, `EXA_API_KEY`) live in the macOS Keychain, encrypted at rest. Store each with `uv run swarm-vault set <NAME>` (it prompts; nothing is echoed or written to disk) and check with `uv run swarm-vault status`. `swarm-api` and `swarm-grpc` load them at start; a variable already in the environment wins, and `~/.env` is a legacy fallback. YAML only names the env var; `.env.example` lists the names.

To use a dedicated Keychain, set `SWARM_KEYCHAIN_PATH` to its absolute path in the owner-only `.env`. Vault reads and writes then target that Keychain. Its password is entered through macOS SecurityAgent when the Keychain is created; it is never passed on the command line.

Inspect the host map and selected backends with:

```bash
uv run python -m swarm_sdk.gpu.report
```

Current `onnxruntime` wheels do not include macOS x86_64, so FastEmbed is skipped on Intel Macs unless ORT is installed another way. Tests inject a local embedder and do not download models.

## Run

```bash
uv run swarm-api
uv run swarm-grpc
```

`POST /v1/runs` with `{"text": "...", "thread_id": "t1"}`. `GET /v1/health`. gRPC `SwarmService.Run` and `SwarmService.Recall` call the same core.

### LangGraph Server

[`langgraph.json`](langgraph.json) deploys both engines as server graphs (factories in [`src/swarm_sdk/server/graphs.py`](src/swarm_sdk/server/graphs.py)):

- `swarm` — the manifest-driven handoff graph (`Agents/{Researcher,Coder,Reviewer}/agent.yaml` set `langgraph_node`; each persona's `AGENTS.md` contract is its system prompt).
- `plan` — goal → `spawn` → wave execution in one graph.

```bash
langgraph up                # deploy locally (the Python 3.14 langgraph-cli has no in-memory `dev`)
SWARM_SERVER_URL=http://127.0.0.1:2024 uv run swarm-api   # or set SWARM_SERVER_URL anywhere:
```

With `SWARM_SERVER_URL` set, `SwarmSDK.run` delegates to the server via the `langgraph_sdk` client (`swarm_sdk.serving.client.run_on_server`) instead of running the graph in-process; threads and checkpoints live server-side. Leave it unset for the built-in FastAPI/gRPC serving.

## Orchestration engine

`swarm_sdk.orchestrator` runs a goal as a parallel multi-agent plan:

1. `spawn(goal, manifests)` — the Orchestrator agent decomposes the goal into a plan via LangChain `with_structured_output` (tool-calling; the JSON-prompt + regex path remains as fallback and behind `SWARM_PLANNER_STRUCTURED_OUTPUT=false`; the one retry includes the rejection reason so the model self-corrects, then it falls back to a single-step plan).
2. `run_plan(plan, factory)` — a LangGraph `StateGraph` executes the plan in dependency waves; steps in the same wave run concurrently via `bounded_gather` (capped by `parallelism.max_concurrency`; uvloop; the runtime thread pool widens automatically on free-threaded Python 3.14). Sibling Coder steps must claim disjoint `files`.
3. Each step is a `WorkerAgent` bound to its `Agents/{Name}/agent.yaml` manifest: model, `think_level`, `effort`, and `token_budget` are pre-selected per agent; the system prompt is the role contract from that agent's `AGENTS.md`; the step prompt carries `task`, claimed `files`, and only its declared `inputs` (dependency outputs), never the whole transcript.

Token savings: shared role-contract prompt cached per process, exact + semantic step cache (`SemanticCache`), hard `max_prompt` packing, and per-step usage totals (`prompt_tokens`, `completion_tokens`, `llm_calls`, `cached_calls`) reported in `PlanResult.usage`.

gRPC: `SwarmService.SpawnPlan` (goal → plan handle), `RunPlan` (handle → per-step outputs + usage), `PlanStatus` (poll for long plans). Manifests set `api_key_env` to the provider variable named by their model route, such as `OPENAI_API_KEY`; secret values stay in the Keychain.

Predefined model routes, API key variable names, and service credential owners live in [`Main/config/model_registry.yaml`](Main/config/model_registry.yaml); it contains no credential values. Runtime defaults live in [`src/swarm_sdk/agents/config/swarm.yaml`](src/swarm_sdk/agents/config/swarm.yaml) (human-facing symlinks under [`Main/config/`](Main/config/)). Per-agent roles, models, and tasks live in [`Agents/{Name}/agent.yaml`](Agents/Tester/agent.yaml) (see [`Agents/README.md`](Agents/README.md)).

**Three parallel agent lanes** (fixed git worktrees; see [`.cursor/skills/multi-lane-worktrees/SKILL.md`](.cursor/skills/multi-lane-worktrees/SKILL.md)):

| Lane | Worktree | Branch |
|------|----------|--------|
| WebSearch | [`WebSearch/`](WebSearch/) | `feature/websearch` — [`PIPELINE.md`](WebSearch/PIPELINE.md) |
| Prediction | `../Swarm-Prediction` | `feat/prediction-engine` — [`Prediction/`](Prediction/) |
| Newsletter | `../Newsletter` | `feat/newsletter` — [`Newsletter/`](Newsletter/) |

Repo root stays on `integration/all-branches` for merges. Open [`codeworkspace/swarm.code-workspace`](codeworkspace/swarm.code-workspace) for a multi-root editor layout. `SWARM_*` env vars override file defaults.

## Token path

1. Exact SHA-256 cache, then a cosine semantic cache (default threshold `0.97`).
2. Router on `think_level: low` with provider fallback and circuit breakers (`GET /v1/health` shows breaker state).
3. Think-level token caps, then tokenizer budget (system prompt, memories, newest turns; tool text capped).
4. Hybrid dense + BM25 recall (RRF), or Mem0 `search_text` when `vectorstore.backend: mem0`; then dedupe, rerank; only top-k snippets injected. The sqlite backend falls back from FTS5 to a token scan when the SQLite build lacks FTS5, and BGE-M3 embeddings skip `query:`/`passage:` prefixes (BGE v1.x keeps them).
5. Near-duplicate memories dropped before the prompt; empty answers are never cached or remembered (no poisoned cache hits).
6. Parallel fan-out with bounded concurrency and JSON briefs (facts carry only summary overflow, no duplication); LangGraph handoffs for sequential specialist work. Handoff nodes are the `Agents/` personas that set `langgraph_node` in `agent.yaml` (see [`Agents/SKILLS.md`](Agents/SKILLS.md)); the router answers via LangChain structured output with JSON-mode + regex fallback. Agents with the `web_search` capability get the WebSearch LangChain tools when `SWARM_ENABLE_WEBSEARCH_TOOLS=true`.

HTTP peers use `httpx2` with HTTP/2 (`h2`). `aiohttp` and `requests` are the other clients.

### RAG options

Opt-in techniques under `rag:` in `swarm.yaml`; all default to off (design and measured results:
`docs/superpowers/specs/2026-10-02-rag-techniques-design.md`).

- `u_shape_order`: put the best recalled memories first and last in the prompt.
- `gate`: drop recalled memories when the best reranker score is below `gate.low`. Thresholds are
  in the reranker's score scale (`KeywordReranker` 0..1, `FastEmbedReranker` raw logits); recalibrate
  them for your reranker.
- `parent_child` / `child_size`: `swarm ingest` indexes small child chunks and returns the parent section.

Measure them offline: `cd Agents && uv run python -m benchmark.Tasks.rag_quality.benchmark_rag_quality`.

The model-effort suite reports exact-answer scores and provider token usage by
task type, model, and configured effort. It measures provider-call time
separately so the average local overhead excludes model wait. Run the scripted
harness with `PYTHONPATH=Agents uv run python -m benchmark.model_effort`; see
[`Agents/benchmark/README.md`](Agents/benchmark/README.md) for the opt-in
autonomous LLM run (`--auto`) and live model selection.

## Checks

Context7, Context.dev, Apify, Bright Data, and Appwrite MCP are configured for
Cursor in [`.cursor/mcp.json`](.cursor/mcp.json) and for Claude Code in
[`.mcp.json`](.mcp.json). Remote HTTP servers send `Authorization: Bearer …`
from env vars (`CONTEXT7_API_KEY`, `CONTEXT_DEV_API_KEY`, `APIFY_TOKEN`);
Bright Data / Appwrite stdio servers take `BRIGHT_DATA_API_TOKEN` and
`APPWRITE_*` (store with `uv run swarm-vault set`, names only in
[`.env.example`](.env.example)). Local Cursor wrappers under `~/.gemini/mcp/`
load the same Keychain services. For Claude Code CLI:

```bash
source scripts/export-mcp-keys.sh
claude
```

Codex runs the official local server through its user MCP configuration
(`codex mcp list` to inspect it). Refresh MCP servers or start a new editor
session after changing these settings.

`ty` resolves the optional-dependency imports (mem0, prometheus_client, OpenCL),
so run the gate with the extras the SDK supports:

```bash
uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 pytest Agents/benchmark -q
uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 ruff check src Agents/benchmark Main
uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 ty check src Agents/benchmark Main
uv run python -m swarm_sdk.agents.validate
```

## Local CPython 3.14.7 runtime

The standalone x86_64 CPython 3.14.7 build is available inside this checkout at
`.runtime/cpython-3.14.7/bin/python3.14` (the local runtime path points to the
installed build under `~/.local/opt`). Select that interpreter when creating a
project virtual environment, for example:

```bash
uv venv --python .runtime/cpython-3.14.7/bin/python3.14 .venv-cpython3147
```

Keep the normal project `.venv` unless you intentionally want to recreate it.
GPU benchmark commands and measured runs are documented in
[`Agents/benchmark/README.md`](Agents/benchmark/README.md); they use the current
project environment.
