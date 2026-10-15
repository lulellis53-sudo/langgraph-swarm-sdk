# Master AI Provider & Account Tier Registry

> **Document Target**: `Agents/ApiVaulter/docs/PROVIDERS_REGISTRY.md`  
> **Authority**: Swarm `ApiVaulter` Infrastructure Agent  
> **Status**: Verified Production Roster (2026-10-14)  
> **Scope**: Exhaustive inventory of all paid plans, credit balances, specialized acceleration hardware, proxy gateways, and dual-tier accounts across Swarm.  
> **Web Searchers Registry**: [`WEBSEARCHERS.md`](./WEBSEARCHERS.md)  
> **Cognitive Memory & Identity Layer**: [`MEMORY_AND_IDENTITY.md`](./MEMORY_AND_IDENTITY.md)

---

## 1. Multi-Tier Provider Classification Matrix

The Swarm routing engine prioritizes execution across four distinct infrastructure tiers based on task criticality, throughput demands, and quota availability:

```text
+===================================================================================+
|               SWARM MULTI-TIER PROVIDER HIERARCHY & ROUTING ENGINE                |
+===================================================================================+

  [Tier 1: Paid Subscriptions & Pro Plans]
  ├── Google AI Studio (Pro Plan) ────────► 2M context, high RPM, Gemini 2.0 Flash/Pro
  ├── Mistral AI (Pro Plan) ──────────────► La Plateforme high concurrency, Large/Codestral
  ├── OpenRouter ($10 Paid Balance) ──────► Priority routing, premium models, higher RPM
  ├── TokenHarbor ($5 Paid Balance) ──────► Expanded multi-model gateway
  ├── Anthropic Claude ───────────────────► Claude 3.5 Sonnet / Haiku / Opus
  ├── OpenAI Codex ───────────────────────► GPT-4o, o1, o3-mini
  ├── Moonshot Kimi ──────────────────────► Kimi 2M long-context Chinese/English
  ├── MiniMax ────────────────────────────► abab6.5, text-01 high-speed multimodal
  ├── Cursor / Cursor Fast ───────────────► Specialized fast completions
  ├── Z.ai (Zhipu AI) ────────────────────► GLM-4 / GLM-Zero reasoning
  ├── Xiaomi Miomo ───────────────────────► MiLM mobile/edge agent models
  └── xAI Grok ───────────────────────────► Grok 2 / Grok 2 mini live reasoning
                      │
                      ▼ (Heavy Batches / Real-Time Low Latency)
  [Tier 2: Ultra-Fast Hardware Acceleration Platforms]
  ├── Cerebras ───────────────────────────► Wafer-Scale Engine, 1,000–2,000 tok/sec
  ├── SambaNova Systems ──────────────────► SN40L Reconfigurable Dataflow, Llama 405B
  ├── Novita AI ──────────────────────────► Scalable GPU cloud, DeepSeek/Qwen 2.5
  ├── StepFlash (StepFun) ────────────────► Step-1/Step-2 fast multimodal reasoning
  ├── Cohere ─────────────────────────────► Command R+, Embed v3, Rerank v3.5
  └── NVIDIA NIM ─────────────────────────► NVIDIA Inference Microservices, Nemotron
                      │
                      ▼ (Gateway Proxies & Specialized Code)
  [Tier 3: Aggregator Proxies & Code Specialists]
  ├── KiloGateway ────────────────────────► Unified multi-endpoint LLM gateway
  ├── Zenmux ─────────────────────────────► High-reliability model routing multiplexer
  ├── OpenCode / OpenCode Zen ────────────► Targeted code synthesis & AST transforms
  ├── Poolside AI ────────────────────────► Next-gen software intelligence models
  └── Ollama Cloud ───────────────────────► Hosted private/custom model instances
                      │
                      ▼ (Rate-Limit / Quota Depletion Failovers)
  [Tier 4: Zero-Cost / Free-Tier Fallbacks]
  ├── Mistral AI (Free Developer Tier) ───► 1 RPS, Codestral / Mistral Nemo
  ├── Google AI Studio (Free Quota) ──────► 1,500 RPD, 15 RPM, Gemini 2.0 Flash
  ├── OpenRouter Free (:free models) ─────► Llama 3.3 70B, DeepSeek R1, Qwen 2.5
  ├── Groq Cloud ─────────────────────────► 14,400 RPD free, Llama 3.3 70B (300+ tok/s)
  └── Cloudflare Workers AI ──────────────► 10,000 Neurons/day free edge models
```

---

## 2. Detailed Provider Profiles & Endpoint Specifications

### Tier 1: Paid Subscriptions & Pro Plans

#### 1. Google AI Studio (Pro Plan)
- **Account Status**: Pro / Pay-as-you-go Plan (Bypass standard free tier 15 RPM cap).
- **Core Models**: `gemini-2.0-flash-exp`, `gemini-1.5-pro`, `gemini-1.5-flash`.
- **Context Window**: 1,048,576 to 2,097,152 tokens.
- **Base URL**: `https://generativelanguage.googleapis.com/v1beta/openai` (OpenAI compatible) or native SDK.
- **Vault Secret Key**: `GOOGLE_API_KEY` / `GEMINI_API_KEY`.
- **Primary Use**: Large-context codebase analysis, multi-file synthesis, fast multimodal reasoning.

#### 2. Mistral AI (Dual Accounts: Pro Plan + Free Plan)
- **Account A (Pro Plan)**:
  - Account Status: "La Plateforme" Paid Tier (Commercial usage, high concurrency).
  - Models: `codestral-latest`, `mistral-large-latest`, `pixtral-large-latest`, `mistral-small-latest`.
  - Base URL: `https://api.mistral.ai/v1` & `https://codestral.mistral.ai/v1`.
  - Vault Secret Key: `MISTRAL_API_KEY_PRO` (aliased to `MISTRAL_API_KEY`).
- **Account B (Free Plan)**:
  - Account Status: Free Developer Plan (1 RPS limit).
  - Models: `codestral-latest`, `open-mistral-nemo`.
  - Vault Secret Key: `MISTRAL_API_KEY_FREE`.
  - Primary Use: Non-critical unit tests and background documentation checks.

#### 3. OpenRouter ($10 Paid Credit Balance)
- **Account Status**: $10 Paid Credit Tier (Unlocks high RPM, no free queue delays).
- **Core Models**: All open weights and proprietary models (`anthropic/claude-3.5-sonnet`, `meta-llama/llama-3.3-70b-instruct`, `deepseek/deepseek-r1`, `qwen/qwen-2.5-coder-32b-instruct`).
- **Base URL**: `https://openrouter.ai/api/v1`.
- **Vault Secret Key**: `OPENROUTER_API_KEY`.
- **Primary Use**: Universal fallback router and access to specialized open-weights checkpoints.

#### 4. TokenHarbor ($5 Paid Credit Balance)
- **Account Status**: $5 Paid Gateway Tier.
- **Core Capabilities**: Multi-model aggregator providing expanded model access and backup routing.
- **Base URL**: Configured gateway endpoint.
- **Vault Secret Key**: `TOKENHARBOR_API_KEY`.
- **Primary Use**: Redundant secondary routing when primary direct endpoints experience outages.

#### 5. Additional Paid Providers (Direct LLM Tier)
| Provider | Target Models | Vault Secret Name | Base URL | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Anthropic Claude** | `claude-3-5-sonnet-latest`, `claude-3-5-haiku` | `CLAUDE_OAUTH_TOKEN` / `ANTHROPIC_API_KEY` | `https://api.anthropic.com/v1` | Primary agent reasoning model |
| **OpenAI / Codex** | `gpt-4o`, `o1`, `o3-mini`, `gpt-4o-mini` | `CODEX_OAUTH_TOKEN` / `OPENAI_API_KEY` | `https://api.openai.com/v1` | Fast code generation & structured tools |
| **Moonshot Kimi** | `moonshot-v1-128k`, `moonshot-v1-auto` | `KIMI_API_KEY` / `MOONSHOT_API_KEY` | `https://api.moonshot.cn/v1` | 2M long-context Chinese/English docs |
| **MiniMax** | `abab6.5s-chat`, `text-01` | `MINIMAX_API_KEY` | `https://api.minimax.chat/v1` | High-speed structured chat |
| **Cursor / Cursor Fast** | Tab completion & fast edits | `CURSOR_API_KEY` | Cursor Internal API | IDE integration agent calls |
| **Z.ai (Zhipu AI)** | `glm-4`, `glm-4-plus`, `glm-zero` | `ZAI_API_KEY` / `ZHIPU_API_KEY` | `https://open.bigmodel.cn/api/paas/v4` | High-level reasoning & math |
| **Xiaomi Miomo** | MiLM mobile & lightweight agent models | `XIAOMI_MIOMO_API_KEY` | Xiaomi AI Gateway | Edge task delegation |
| **xAI Grok** | `grok-2`, `grok-2-mini` | `XAI_API_KEY` / `GROK_API_KEY` | `https://api.x.ai/v1` | Real-time web-grounded reasoning |

---

### Tier 2: Ultra-Fast Hardware Acceleration Platforms

| Provider | Acceleration Hardware | Key Models | Throughput (Tokens/s) | Vault Secret Name | Base URL |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Cerebras** | Wafer-Scale Engine (CS-3) | `llama3.1-8b`, `llama3.1-70b` | 1,000 – 2,100 tok/s | `CEREBRAS_API_KEY` | `https://api.cerebras.ai/v1` |
| **SambaNova** | SN40L Reconfigurable Dataflow | `Meta-Llama-3.1-405B`, `70B` | 400 – 800 tok/s | `SAMBANOVA_API_KEY` | `https://api.sambanova.ai/v1` |
| **Novita AI** | Scalable GPU Cloud | `deepseek-chat`, `qwen-2.5-72b` | 200 – 400 tok/s | `NOVITA_API_KEY` | `https://api.novita.ai/v3/openai` |
| **StepFlash (StepFun)** | Step-1 / Step-2 Tensor Engine | `step-1-8k`, `step-1-flash` | 300 – 500 tok/s | `STEPFLASH_API_KEY` | `https://api.stepfun.com/v1` |
| **Cohere** | TPU / GPU Cloud | `command-r-plus`, `embed-v3` | Enterprise RAG | `COHERE_API_KEY` | `https://api.cohere.com/v2` |
| **NVIDIA NIM** | Hopper H100 / Blackwell B200 | `meta/llama-3.1-405b-instruct` | Cloud Microservices | `NVIDIA_NIM_API_KEY` | `https://integrate.api.nvidia.com/v1` |

---

### Tier 3: Aggregator Proxies & Code Specialists

- **KiloGateway**: Multi-endpoint proxy gateway for dynamic load balancing (`KILOGATEWAY_API_KEY`).
- **Zenmux**: Model multiplexer providing transparent failover across providers (`ZENMUX_API_KEY`).
- **OpenCode & OpenCode Zen**: Specialized code generation gateways (`OPENCODE_API_KEY`).
- **Poolside AI**: Code-first foundation models for deep programming tasks (`POOLSIDE_API_KEY`).
- **Ollama Cloud**: Cloud-hosted instances of quantized open-weights models (`OLLAMA_CLOUD_API_KEY`).

---

## 3. Dynamic Multi-Tier Routing Rules

`ApiVaulter` applies the following priority policy when handling requests from peer agents:

1. **High-Priority & Architecture Tasks**:
   - Route to **Tier 1**: Google AI Studio (Pro Plan) or Claude 3.5 Sonnet.
2. **High-Throughput Batch & Fast Refactoring Tasks**:
   - Route to **Tier 2**: Cerebras (`llama3.1-70b` at 1,500 tok/s) or SambaNova (`Llama-3.1-405B`).
3. **Coding & AST Transformations**:
   - Route to **Tier 1 / 3**: Mistral AI (Pro - `codestral-latest`), OpenCode Zen, or OpenRouter (`qwen-2.5-coder-32b`).
4. **Rate-Limit / Quota Depletion Failover**:
   - On HTTP 429: Failover sequentially:
     `Tier 1 (Pro)` $\rightarrow$ `Tier 2 (Cerebras/SambaNova)` $\rightarrow$ `OpenRouter ($10 Paid)` $\rightarrow$ `Tier 4 (Daily Free / Groq / Gemini Free)`.
5. **Cost Optimization Mode (TokenSaver Active)**:
   - Route non-critical background audits to **Tier 4** (Zero-Cost / Daily Free models) to preserve paid credits.

---

## 4. Web Searchers & Retrieval Engines Roster

Detailed API specifications, MCP schemas, CLI commands, and official documentation are indexed in [`WEBSEARCHERS.md`](./WEBSEARCHERS.md):

| Search / Retrieval Provider | Specialization | MCP Server | Canonical Secret Key | Base URL / Entrypoint |
| :--- | :--- | :--- | :--- | :--- |
| **Jina AI** | URL-to-Markdown, Search, Embeddings | `jina` / `web-reader` | `JINA_API_KEY` | `https://s.jina.ai/` & `https://r.jina.ai/` |
| **Context** | Live web, brand search, web-answers | `context` | `CONTEXT_API_KEY` | `https://api.context.dev/v1/` |
| **You.com** | Web search, Smart search, Research | `you-search` | `YDC_API_KEY` | `https://api.ydc-index.io/search` |
| **Context7** | Framework & library documentation | `context7` | `CONTEXT7_API_KEY` | `https://api.context7.ai/v1/` |
| **Exa** | Neural semantic search, web fetch | `exa` | `EXA_API_KEY` | `https://api.exa.ai/search` |
| **Apify** | Actor automation, crawling, scraping | `apify` | `APIFY_TOKEN` | `https://api.apify.com/v2/` |
| **Tavily** | Agent search, extract, research | `tavily` | `TAVILY_API_KEY` | `https://api.tavily.com/search` |
| **Brave Search** | Independent web index, summarizer | `brave` / `brave-search` | `BRAVE_API_KEY` | `https://api.search.brave.com/res/v1/` |
| **ParallelAI** | Parallel queries, Playwright fleet | `playwright` / `parallel`| `PARALLEL_API_KEY` | `https://api.parallel.ai/v1/` |
| **Bright Data** | Web Unlocker, SERP API, scrapers | `bright-data` | `BRIGHT_DATA_API_TOKEN` | `https://api.brightdata.com/` |
| **DuckDuckGo** | Zero-cost privacy web search | `duckduckgo` | None (Free Fallback) | `https://html.duckduckgo.com/html/` |

---

## 5. Cognitive Memory & System Identity Layer

Detailed architecture, MCP tool schemas, and CLI workflows are indexed in [`MEMORY_AND_IDENTITY.md`](./MEMORY_AND_IDENTITY.md):

| Component / Layer | Role & Function | Integration / MCP Server | Canonical Secret Key | Endpoint / Storage |
| :--- | :--- | :--- | :--- | :--- |
| **JEV** | Sovereign user authority & System-1 decision router | `swarm_sdk.core.jev_router.JevRouter` | `JEV_API_KEY` / `TYPESAFE_API_KEY` | `https://api.typesafe.ai` (`jev-latest`) |
| **Mem0** | Long-term contextual user and conversational memory | `mem0` (`add-memory`, `search-memories`) | `MEM0_API_KEY` | `https://api.mem0.ai/v1` |
| **Supermemory** | Persistent project knowledge and bookmark memory | `supermemory` (`supermemory_add`, `supermemory_search`)| `SUPERMEMORY_API_KEY` | `https://api.supermemory.ai/v1` |


