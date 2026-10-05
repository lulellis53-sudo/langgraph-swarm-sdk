# Models

One note for the paid Swarm routes and the free-catalog snapshot. Both were taken on 2026-10-05. Paidmodels is the live chat wiring in `src/swarm_sdk/agents/config/model_registry.yaml` and `providers.yaml`. Free models is a public-list snapshot. That snapshot did not add routes.

Credential values stay in the vault. This file stores env names only.

## Paidmodels

Paid chat routes for Codex, Grok, Claude, MiniMax, Z.ai, Kimi, and Xiaomi MiMo. Priorities are unchanged: the lowest number still wins a generic think-level pick, so `zai:glm-5.2` (priority 5) wins before these other rows.

OAuth means the credential env name below.

### OAuth

| Family | Route | Provider | Credential | Effort | Priority |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Codex | `openai:gpt-6-luna` | `codex` | `CODEX_OAUTH_TOKEN` | medium | 25 |
| Grok | `xai:grok-4.6` | `xai` | `GROK_OAUTH_TOKEN`, then `XAI_API_KEY` | medium | 18 |
| Claude | `anthropic:claude-sonnet-4.6` | `claude-code` | `CLAUDE_OAUTH_TOKEN`, then `CLAUDE_CODE_API_KEY` | medium | 30 |
| Claude Opus 5.5 | `anthropic:claude-opus-5-5` | `claude-code` | `CLAUDE_OAUTH_TOKEN`, then `CLAUDE_CODE_API_KEY` | medium | 31 |

`providers.yaml` and the agent manifests already name `CODEX_OAUTH_TOKEN`, `GROK_OAUTH_TOKEN`, and `CLAUDE_OAUTH_TOKEN`. The chat registry reads those names first.

`swarm.yaml` sends `off`, `low`, and `medium` to Codex (`openai:gpt-6-luna`, priority 10 in that file) and `medium`, `high`, and `xhigh` to Claude (`anthropic:claude-sonnet-4.6`, priority 20 in that file). Grok is a registry route and is not in that selector list.

Codex and Claude have no `base_url_env` on these rows. Grok has none either. The native client receives the vault value as `api_key` (Codex, model prefix `openai`), `xai_api_key` (Grok), or `anthropic_api_key` (Claude).

### API key

| Family | Route | Provider | Credential | Base URL | Effort | Priority |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Z.ai | `zai:glm-5.2` | `zai` | `ZHIPU_API_KEY`, then `ZAI_API_KEY` | `ZAI_BASE_URL`, default `https://api.z.ai/api/paas/v4` | medium | 5 |
| Kimi | `moonshot:kimi-k2.7-code` | `moonshot` | `KIMI_API_KEY`, then `KIMI_API_KEY_DUPLICATE_1`, then `KIMI_CODE_PLAN_API_KEY` | `MOONSHOT_BASE_URL`, default `https://api.moonshot.ai/v1` | medium | 10 |
| Kimi | `moonshot:kimi-k2.7-code-b` | `moonshot` | `KIMI_API_KEY_DUPLICATE_1` | same host; `model_id` is `kimi-k2.7-code` | medium | 11 |
| Xiaomi MiMo | `xiaomi:mimo-v2.5-pro` | `xiaomi` | `MIMO_API_KEY` | `MIMO_BASE_URL` (required; no default in `chat.py`) | medium | 15 |
| MiniMax | `minimax:minimax-2.7-high-speed` | `minimax` | `MINIMAX_API_KEY` | `MINIMAX_BASE_URL`, default `https://api.minimax.io/v1` | medium | 20 |

Z.ai, Kimi, Xiaomi MiMo, and MiniMax are OpenAI-compatible. Chat posts to `{base}/chat/completions`.

`providers.yaml` still lists MiniMax as `minimax:MiniMax-M2.7`. The chat loader uses the registry id `minimax:minimax-2.7-high-speed`. That registry id is marked assumed until it is checked in the MiniMax console. This file does not rename it.

Xiaomi MiMo has no default host in `chat.py`. A call needs `MIMO_BASE_URL` stored in the vault. The registry comment says to confirm that host against Xiaomi's docs.

## Free models

Snapshot taken 2026-10-05 16:50 UTC. Prices move. Re-fetch the two public lists before relying on an ID.

Nothing in this section was added as a route.

Sources, fetched with no API key:

- Novita list: `GET https://api.novita.ai/openai/v1/models` (121 models, HTTP 200 at 16:50:35 UTC). Chat base is `https://api.novita.ai/openai`.
- OpenRouter catalog: `GET https://openrouter.ai/api/v1/models` (465 models). Provider names come from `GET https://openrouter.ai/api/v1/models/{id}/endpoints`.
- OpenRouter decisions, where Jev lives: `GET https://openrouter.ai/api/v1/models?output_modalities=decisions` (13 models).

Novita’s integer price is USD per million tokens times 10,000. `1500` is `$0.15`. A model counts as free here only when both integers are `0`, `pricing` is null, and `is_tiered_billing` is false.

OpenRouter’s `pricing.prompt` and `pricing.completion` are USD per token. `0.000000042` is `$0.042` per million. A text model counts as free when both fields are the string `"0"`. The string `"-1"` is the router sentinel (same value as `openrouter/auto`). It is not `$0`.

### Novita: $0 on the public list

Five of 121 models. All `model_type: chat`, `status: 1`.

| Model ID | Context | Max output | Modalities | API shapes |
| --- | ---: | ---: | --- | --- |
| `apodex/apodex-1.1-mini` | 262144 | 262144 | text to text | chat, Anthropic, responses |
| `bunny` | 262144 | 32768 | text to text | chat |
| `dev/glm46` | 256000 | 256000 | text to text | chat, Anthropic |
| `inclusionai/ling-3.0-flash-sante` | 262144 | 32768 | text to text | chat, Anthropic |
| `inclusionai/ling-3.1-flash` | 262144 | 32768 | text to text | chat, Anthropic |

`bunny` and `dev/glm46` have an empty description. `dev/glm46` is a dev ID that the list still marks active and `$0`. The Ling 3.1 Flash description says a 1M-token window. The catalog field `context_size` is 262144. Use the catalog field.

These five also have a `$0` OpenRouter row, except `bunny` and `dev/glm46`, which were not in the OpenRouter catalog:

| OpenRouter ID | Endpoint | Prompt / completion |
| --- | --- | --- |
| `inclusionai/ling-3.1-flash` | Novita | `$0` / `$0` |
| `inclusionai/ling-3.0-flash-sante:free` | Novita | `$0` / `$0` |
| `apodex/apodex-1.1-mini:free` | Novita (`novita/bf16`) | `$0` / `$0` |

### Novita: headline `0` that is still billed

`qwen/qwen3.5-plus` and `qwen/qwen3.6-plus` publish input and output integers of `0` because `is_tiered_billing` is true. The tiers are the price. Context on both is 1,000,000. Max output is 65,536.

`qwen/qwen3.5-plus`, USD per million tokens:

| Prompt tokens in the request | Input | Output |
| --- | ---: | ---: |
| 1 to 256,000 | $0.40 | $2.40 |
| 256,000 to 1,000,000 | $0.50 | $3.00 |

`qwen/qwen3.6-plus`, USD per million tokens:

| Prompt tokens in the request | Input | Output | Cache read | Cache write |
| --- | ---: | ---: | ---: | ---: |
| 1 to 262,144 | $0.50 | $3.00 | $0.05 | $0.625 |
| 262,144 to 1,000,000 | $2.00 | $6.00 | $0.20 | $2.50 |

Ling 3.0 Flash VL is not free on this snapshot. A Novita post had offered it at `$0` through 2026-09-23 02:30 UTC. That window is over. Live integers `750` / `2200` are `$0.075` / `$0.22` per million. `inclusionai/ling-3.0-flash` is `$0.06` / `$0.18` (`600` / `1800`).

### OpenRouter Jev

Three different IDs. Only the decision model has a normal token price. The router does not.

| ID | What it is | Context | Price per million | Endpoints API |
| --- | --- | ---: | --- | --- |
| `typesafe/jev-router` | Chat router. It picks another model and a reasoning effort. | 1,000,000 | `prompt` and `completion` are `"-1"` | no endpoints |
| `typesafe/jev-1.13` | Decision model (Choice, Noul, Score). Not a chat model. It is absent from the default 465-model list and present on the decisions query. | 32,000 | $0.042 input, $0 output | TypeSafe |
| `~typesafe/jev-latest` | Alias that redirects to the latest Jev decision model. | 32,000 | $0.042 input, $0 output | no endpoints of its own |

`typesafe/jev-router` is the only Jev row in the default catalog. `"-1"` / `"-1"` matches `openrouter/auto`, `openrouter/fusion`, `openrouter/pareto-code`, `openrouter/bodybuilder`, `openrouter/auto-beta`, and `nvidia/switchyard`. You pay the model the router selects. The OpenRouter model page FAQ says the router price shown there is zero. The models API does not say that. Use the API.

Router usage is `model: "typesafe/jev-router"` on `POST https://openrouter.ai/api/v1/chat/completions`. Docs: `https://openrouter.ai/docs/guides/routing/routers/jev-router`. The decision model is `typesafe/jev-1.13` on the Decisions API, not Chat Completions. Docs: `https://openrouter.ai/docs/guides/community/jev`.

Swarm’s Jev client posts to TypeSafe `https://api.typesafe.ai/v1/systemone` with `JEV_API_KEY`. That client is not `typesafe/jev-router` and not an OpenRouter call.

### OpenRouter: prompt and completion both `"0"`

21 models in the default catalog. `top_provider.name` is empty on every one of these rows. The provider column is the endpoints API.

| Model ID | Provider | Context | Max completion | Modality | Expires |
| --- | --- | ---: | ---: | --- | --- |
| `apodex/apodex-1.1-mini:free` | Novita | 262144 | 235929 | text to text | |
| `cohere/north-mini-code:free` | Cohere | 256000 | 64000 | text to text | |
| `dots-studio/dots-3-note-preview:free` | AtlasCloud | 512000 | 460800 | text and image to text | 2026-12-31 |
| `google/gemma-4-26b-a4b-it:free` | Google AI Studio | 262144 | 32768 | text, image, and video to text | |
| `google/gemma-4-31b-it:free` | Google AI Studio | 262144 | 32768 | text, image, and video to text | |
| `google/lyria-3-clip-preview` | Google AI Studio | 1048576 | 65536 | text and image to text and audio | |
| `google/lyria-3-pro-preview` | Google AI Studio | 1048576 | 65536 | text and image to text and audio | |
| `inclusionai/ling-3.0-flash-sante:free` | Novita | 262144 | 32768 | text to text | |
| `inclusionai/ling-3.1-flash` | Novita | 262144 | 32768 | text to text | |
| `liquid/lfm-2.5-2.6b:free` | Liquid | 65536 | 8192 | text to text | |
| `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` | Nvidia | 256000 | 65536 | text, image, audio, and video to text | |
| `nvidia/nemotron-3-super-120b-a12b:free` | Nvidia | 262144 | 235929 | text to text | |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | Nvidia | 1000000 | 65536 | text to text | |
| `nvidia/nemotron-3.5-content-safety:free` | Nvidia | 128000 | 8192 | text and image to text | |
| `nvidia/nemotron-3.5-lightning:free` | Nvidia | 1000000 | 65536 | text to text | |
| `openrouter/free` | router over free models | 200000 | | text and image to text | |
| `poolside/laguna-s-2.1:free` | Poolside | 262144 | 32768 | text to text | 2026-10-31 |
| `poolside/laguna-xs-2.1:free` | Poolside | 262144 | 32768 | text to text | 2026-10-31 |
| `qwen/qwen3.8-27b:free` | ModelRun | 262144 | 235929 | text, image, and video to text | |
| `thinkingmachines/inkling-small:free` | Thinking Machines | 1048576 | 262144 | text, image, and audio to text | |
| `thinkingmachines/inkling:free` | Thinking Machines | 1048576 | 262144 | text, image, and audio to text | |

`openrouter/free` selects a free model at random. Its own endpoints list is empty. The Lyria rows are audio models with a `$0` token price, not chat models.

Two more `$0` / `$0` rows show up only on the decisions query:

| Model ID | Provider | Context | Notes |
| --- | --- | ---: | --- |
| `inception/mercury-decide:free` | Inception | 32768 | decision model |
| `respan/span-01-lite:free` | Respan | 0 | decision model; the API publishes context length `0` |

Other decision models have free output and a paid input. They are not in the table above. Jev 1.13 is one of them (`$0.042` / `$0`).

### Swarm routes that look related

Checked against the same OpenRouter catalog. These stay as they are.

| Swarm route | OpenRouter fact on this snapshot |
| --- | --- |
| `openrouter:z-ai/glm-5.3-flash` | Not free. `$0.15` input and `$0.50` output per million (`0.00000015` / `0.0000005` per token). |
| `atlascloud:dots-studio/dots-3-note-prev-free` | Direct Atlas ID. OpenRouter’s `$0` SKU is `dots-studio/dots-3-note-preview:free` on AtlasCloud, expiring 2026-12-31. |
| `poolside:poolside/laguna-s-2.1` | Direct Poolside ID. OpenRouter also has `poolside/laguna-s-2.1` at `$0.09` / `$0.18` per million, and `poolside/laguna-s-2.1:free` at `$0` / `$0`. Both OpenRouter rows expire 2026-10-31. |
| `nvidia:nemotron-3.5-lightning-30b-a3b` | Direct NIM ID. OpenRouter’s `$0` SKU is `nvidia/nemotron-3.5-lightning:free`. The non-free OpenRouter ID is `$0.06` / `$0.16` per million. |

## Agent models

One model per folder under `Agents/`. Context length is `token_budget.max_prompt`. Max token is `token_budget.max_completion`. The API column is the credential env name. The endpoint is the official chat URL checked on 2026-10-05, also stored as `# api_endpoint` in each `agent.yaml`.

Codex, Grok, and Claude have no `base_url_env` in the registry. Codex uses the OpenAI client default `POST https://api.openai.com/v1/chat/completions` with `CODEX_OAUTH_TOKEN`. Grok's verified chat URL is `POST https://api.x.ai/v1/chat/completions` (`https://api.x.ai/docs/`); xAI also documents `POST https://api.x.ai/v1/responses`. Claude is `POST https://api.anthropic.com/v1/messages` (`https://platform.claude.com/docs/en/api/http/messages/create`).

Xiaomi MiMo is not assigned. `chat.py` has no default host for it.

`minimax:minimax-2.7-high-speed` is still the assumed registry id.

| Agent | Model | Effort | Context | Max token | API | API endpoint |
| :--- | :--- | :--- | ---: | ---: | :--- | :--- |
| `ApiDesigner` | `anthropic:claude-sonnet-4.6` | high | 8192 | 2048 | `CLAUDE_OAUTH_TOKEN` | `POST https://api.anthropic.com/v1/messages` |
| `Architect` | `anthropic:claude-sonnet-4.6` | high | 8192 | 2048 | `CLAUDE_OAUTH_TOKEN` | `POST https://api.anthropic.com/v1/messages` |
| `Benchmarker` | `openai:gpt-6-luna` | medium | 4096 | 1024 | `CODEX_OAUTH_TOKEN` | `POST https://api.openai.com/v1/chat/completions` |
| `Coder` | `anthropic:claude-sonnet-4.6` | high | 8192 | 2048 | `CLAUDE_OAUTH_TOKEN` | `POST https://api.anthropic.com/v1/messages` |
| `Compilator` | `anthropic:claude-sonnet-4.6` | high | 8192 | 2048 | `CLAUDE_OAUTH_TOKEN` | `POST https://api.anthropic.com/v1/messages` |
| `DataEngineer` | `openai:gpt-6-luna` | medium | 4096 | 1024 | `CODEX_OAUTH_TOKEN` | `POST https://api.openai.com/v1/chat/completions` |
| `Debugger` | `openai:gpt-6-luna` | high | 4096 | 1024 | `CODEX_OAUTH_TOKEN` | `POST https://api.openai.com/v1/chat/completions` |
| `DeepResearch` | `zai:glm-5.2` | high | 16384 | 8192 | `ZHIPU_API_KEY` | `POST https://api.z.ai/api/paas/v4/chat/completions` |
| `DevOps` | `openai:gpt-6-luna` | medium | 4096 | 1024 | `CODEX_OAUTH_TOKEN` | `POST https://api.openai.com/v1/chat/completions` |
| `Documenter` | `openai:gpt-6-luna` | low | 2048 | 512 | `CODEX_OAUTH_TOKEN` | `POST https://api.openai.com/v1/chat/completions` |
| `MLSpecialist` | `anthropic:claude-sonnet-4.6` | high | 8192 | 2048 | `CLAUDE_OAUTH_TOKEN` | `POST https://api.anthropic.com/v1/messages` |
| `ModelDelegate/Embedder` | `cohere:command-r7b` | low | 2048 | 512 | `COHERE_API_KEY_2` | `POST https://api.cohere.com/v2/chat` |
| `ModelDelegate/FallbackResolver` | `sambanova:Meta-Llama-3.3-70B-Instruct` | medium | 4096 | 1024 | `SAMBANOVA_API_KEY` | `POST https://api.sambanova.ai/v1/chat/completions` |
| `ModelDelegate/MathWorker` | `moonshot:kimi-k2.7-code` | low | 4096 | 2048 | `KIMI_API_KEY` | `POST https://api.moonshot.ai/v1/chat/completions` |
| `ModelDelegate/Router` | `openrouter:z-ai/glm-5.3-flash` | low | 2048 | 512 | `OPENROUTER_API_KEY` | `POST https://openrouter.ai/api/v1/chat/completions` |
| `ModelDelegate` | `openrouter:z-ai/glm-5.3-flash` | low | 4096 | 1024 | `OPENROUTER_API_KEY` | `POST https://openrouter.ai/api/v1/chat/completions` |
| `Newsletter` | `openai:gpt-6-luna` | low | 4096 | 2048 | `CODEX_OAUTH_TOKEN` | `POST https://api.openai.com/v1/chat/completions` |
| `Normalizer` | `atlascloud:dots-studio/dots-3-note-prev-free` | low | 16384 | 512 | `ATLASCLOUD_API_KEY` | `POST https://api.atlascloud.ai/v1/chat/completions` |
| `Optimizer` | `openai:gpt-6-luna` | medium | 4096 | 1024 | `CODEX_OAUTH_TOKEN` | `POST https://api.openai.com/v1/chat/completions` |
| `Orchestrator` | `anthropic:claude-opus-5-5` | medium | 8192 | 2048 | `CLAUDE_OAUTH_TOKEN` | `POST https://api.anthropic.com/v1/messages` |
| `Persister` | `atlascloud:dots-studio/dots-3-note-prev-free` | low | 16384 | 512 | `ATLASCLOUD_API_KEY` | `POST https://api.atlascloud.ai/v1/chat/completions` |
| `Planner` | `openai:gpt-6-luna` | high | 8192 | 2048 | `CODEX_OAUTH_TOKEN` | `POST https://api.openai.com/v1/chat/completions` |
| `Prediction` | `minimax:minimax-2.7-high-speed` | medium | 4096 | 2048 | `MINIMAX_API_KEY` | `POST https://api.minimax.io/v1/chat/completions` |
| `RAG` | `moonshot:kimi-k2.7-code` | high | 16384 | 8192 | `KIMI_API_KEY` | `POST https://api.moonshot.ai/v1/chat/completions` |
| `Refactor` | `anthropic:claude-sonnet-4.6` | high | 8192 | 2048 | `CLAUDE_OAUTH_TOKEN` | `POST https://api.anthropic.com/v1/messages` |
| `Researcher` | `openai:gpt-6-luna` | medium | 4096 | 1024 | `CODEX_OAUTH_TOKEN` | `POST https://api.openai.com/v1/chat/completions` |
| `Reviewer` | `anthropic:claude-sonnet-4.6` | high | 8192 | 2048 | `CLAUDE_OAUTH_TOKEN` | `POST https://api.anthropic.com/v1/messages` |
| `Security` | `anthropic:claude-sonnet-4.6` | high | 8192 | 2048 | `CLAUDE_OAUTH_TOKEN` | `POST https://api.anthropic.com/v1/messages` |
| `Tester` | `openai:gpt-6-luna` | medium | 4096 | 1024 | `CODEX_OAUTH_TOKEN` | `POST https://api.openai.com/v1/chat/completions` |
| `Tuner` | `xai:grok-4.6` | medium | 8192 | 2048 | `GROK_OAUTH_TOKEN` | `POST https://api.x.ai/v1/chat/completions` |
| `TxtToCsv` | `openai:gpt-6-luna` | low | 2048 | 512 | `CODEX_OAUTH_TOKEN` | `POST https://api.openai.com/v1/chat/completions` |
| `WebFetch` | `atlascloud:dots-studio/dots-3-note-prev-free` | low | 16384 | 512 | `ATLASCLOUD_API_KEY` | `POST https://api.atlascloud.ai/v1/chat/completions` |
| `WebResearcher` | `openai:gpt-6-luna` | medium | 4096 | 1024 | `CODEX_OAUTH_TOKEN` | `POST https://api.openai.com/v1/chat/completions` |
| `math` | `moonshot:kimi-k2.7-code` | high | 8192 | 2048 | `KIMI_API_KEY` | `POST https://api.moonshot.ai/v1/chat/completions` |
