# Free models

Snapshot taken 2026-10-05 16:50 UTC. Prices move. Re-fetch the two public lists before relying on an ID.

This file does not change the Swarm registry. Nothing here was added as a route.

Sources, fetched with no API key:

- Novita list: `GET https://api.novita.ai/openai/v1/models` (121 models, HTTP 200 at 16:50:35 UTC). Chat base is `https://api.novita.ai/openai`.
- OpenRouter catalog: `GET https://openrouter.ai/api/v1/models` (465 models). Provider names come from `GET https://openrouter.ai/api/v1/models/{id}/endpoints`.
- OpenRouter decisions, where Jev lives: `GET https://openrouter.ai/api/v1/models?output_modalities=decisions` (13 models).

Novita’s integer price is USD per million tokens times 10,000. `1500` is `$0.15`. A model counts as free here only when both integers are `0`, `pricing` is null, and `is_tiered_billing` is false.

OpenRouter’s `pricing.prompt` and `pricing.completion` are USD per token. `0.000000042` is `$0.042` per million. A text model counts as free when both fields are the string `"0"`. The string `"-1"` is the router sentinel (same value as `openrouter/auto`). It is not `$0`.

## Novita: $0 on the public list

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

## Novita: headline `0` that is still billed

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

## OpenRouter Jev

Three different IDs. Only the decision model has a normal token price. The router does not.

| ID | What it is | Context | Price per million | Endpoints API |
| --- | --- | ---: | --- | --- |
| `typesafe/jev-router` | Chat router. It picks another model and a reasoning effort. | 1,000,000 | `prompt` and `completion` are `"-1"` | no endpoints |
| `typesafe/jev-1.13` | Decision model (Choice, Noul, Score). Not a chat model. It is absent from the default 465-model list and present on the decisions query. | 32,000 | $0.042 input, $0 output | TypeSafe |
| `~typesafe/jev-latest` | Alias that redirects to the latest Jev decision model. | 32,000 | $0.042 input, $0 output | no endpoints of its own |

`typesafe/jev-router` is the only Jev row in the default catalog. `"-1"` / `"-1"` matches `openrouter/auto`, `openrouter/fusion`, `openrouter/pareto-code`, `openrouter/bodybuilder`, `openrouter/auto-beta`, and `nvidia/switchyard`. You pay the model the router selects. The OpenRouter model page FAQ says the router price shown there is zero. The models API does not say that. Use the API.

Router usage is `model: "typesafe/jev-router"` on `POST https://openrouter.ai/api/v1/chat/completions`. Docs: `https://openrouter.ai/docs/guides/routing/routers/jev-router`. The decision model is `typesafe/jev-1.13` on the Decisions API, not Chat Completions. Docs: `https://openrouter.ai/docs/guides/community/jev`.

Swarm’s Jev client posts to TypeSafe `https://api.typesafe.ai/v1/systemone` with `JEV_API_KEY`. That client is not `typesafe/jev-router` and not an OpenRouter call.

## OpenRouter: prompt and completion both `"0"`

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

## Swarm routes that look related

Checked against the same OpenRouter catalog. These stay as they are.

| Swarm route | OpenRouter fact on this snapshot |
| --- | --- |
| `openrouter:z-ai/glm-5.3-flash` | Not free. `$0.15` input and `$0.50` output per million (`0.00000015` / `0.0000005` per token). |
| `atlascloud:dots-studio/dots-3-note-prev-free` | Direct Atlas ID. OpenRouter’s `$0` SKU is `dots-studio/dots-3-note-preview:free` on AtlasCloud, expiring 2026-12-31. |
| `poolside:poolside/laguna-s-2.1` | Direct Poolside ID. OpenRouter also has `poolside/laguna-s-2.1` at `$0.09` / `$0.18` per million, and `poolside/laguna-s-2.1:free` at `$0` / `$0`. Both OpenRouter rows expire 2026-10-31. |
| `nvidia:nemotron-3.5-lightning-30b-a3b` | Direct NIM ID. OpenRouter’s `$0` SKU is `nvidia/nemotron-3.5-lightning:free`. The non-free OpenRouter ID is `$0.06` / `$0.16` per million. |
