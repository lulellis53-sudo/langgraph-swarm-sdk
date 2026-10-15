# Daily Free Tier Models Catalog & Dynamic Failover Reference

> **Document Target**: `Agents/ApiVaulter/docs/PROVIDERSFREEMODELS.md`  
> **Authority**: Swarm `ApiVaulter` Infrastructure Agent  
> **Status**: Verified Active (2026-10-14) | Zero Token Cost  
> **Scope**: Authoritative registry of daily free-tier model endpoints, token allowances, rate limits, and automated fallback routes for Swarm agents.

---

## 1. Multi-Provider Daily Free Tier Matrix

The following models provide zero-cost API access within documented daily rate limits:

| Provider | Model Identifier | Architecture / Specs | Free Rate Limits (RPM / RPD / TPM) | Max Context | Base URL / API Standard |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Google AI Studio** | `gemini-2.0-flash-exp` | Next-gen multimodal / fast agentic | 15 RPM · 1,500 RPD · 1,000,000 TPM | 1,048,576 | `https://generativelanguage.googleapis.com/v1beta/openai` |
| **Google AI Studio** | `gemini-1.5-flash` | High-efficiency multimodal | 15 RPM · 1,500 RPD · 1,000,000 TPM | 1,048,576 | `https://generativelanguage.googleapis.com/v1beta/openai` |
| **Google AI Studio** | `gemini-1.5-flash-8b` | Ultra-lightweight utility | 15 RPM · 1,500 RPD · 1,000,000 TPM | 1,048,576 | `https://generativelanguage.googleapis.com/v1beta/openai` |
| **Groq Cloud** | `llama-3.3-70b-versatile` | Meta Llama 3.3 70B dense | 30 RPM · 14,400 RPD · 6,000 TPM | 128,000 | `https://api.groq.com/openai/v1` |
| **Groq Cloud** | `llama-3.1-8b-instant` | Meta Llama 3.1 8B fast | 30 RPM · 14,400 RPD · 30,000 TPM | 128,000 | `https://api.groq.com/openai/v1` |
| **Groq Cloud** | `mixtral-8x7b-32768` | MoE 8x7B (46.7B sparse) | 30 RPM · 14,400 RPD · 5,000 TPM | 32,768 | `https://api.groq.com/openai/v1` |
| **Groq Cloud** | `gemma2-9b-it` | Google Gemma 2 9B instruction | 30 RPM · 14,400 RPD · 15,000 TPM | 8,192 | `https://api.groq.com/openai/v1` |
| **Mistral AI** | `codestral-latest` | Dedicated code generation 22B | 1 RPS (~60 RPM) · Tier Free limits | 32,768 | `https://codestral.mistral.ai/v1` |
| **Mistral AI** | `open-mistral-nemo` | Mistral Nemo 12B general | 1 RPS (~60 RPM) · Tier Free limits | 128,000 | `https://api.mistral.ai/v1` |
| **OpenRouter** | `meta-llama/llama-3.3-70b-instruct:free` | Llama 3.3 70B open route | 20 RPM · 200 RPD | 128,000 | `https://openrouter.ai/api/v1` |
| **OpenRouter** | `google/gemini-2.0-flash-exp:free` | Gemini 2.0 Flash open route | 20 RPM · 200 RPD | 1,048,576 | `https://openrouter.ai/api/v1` |
| **OpenRouter** | `qwen/qwen-2.5-coder-32b-instruct:free` | State-of-the-art coding 32B | 20 RPM · 200 RPD | 32,768 | `https://openrouter.ai/api/v1` |
| **OpenRouter** | `deepseek/deepseek-r1:free` | DeepSeek R1 reasoning free | 20 RPM · 200 RPD | 64,000 | `https://openrouter.ai/api/v1` |
| **Cloudflare** | `@cf/meta/llama-3.1-8b-instruct` | Serverless edge inference | 10,000 Neurons/day free | 8,192 | `https://api.cloudflare.com/client/v4` |
| **Cohere** | `command-r-plus-08-2024` | Enterprise tool-use & RAG | 20 RPM · 1,000 calls/month | 128,000 | `https://api.cohere.com/v2` |

---

## 2. Inter-Agent Failover & Usage Repair Protocol

When any Swarm agent encounters rate limits, authentication failures, or endpoint depreciation, it invokes `ApiVaulter`:

```text
+===================================================================================+
|               INTER-AGENT API REPAIR & USAGE FAILOVER WORKFLOW                    |
+===================================================================================+

   [Calling Agent: Coder / ModelDelegate / Writer]
                         │
                         ├─► API Call Failed: HTTP 401 / 403 (Authentication Error)
                         │       │
                         │       ▼
                         │   [Invoke ApiVaulter: task=fix_api_key]
                         │   - Rotates key from macOS Keychain or 1Password
                         │   - Runs non-destructive health probe (curl / xh)
                         │   - Returns refreshed credential to caller
                         │
                         └─► API Call Failed: HTTP 429 (Rate Limit / Quota Exhaustion)
                                 │
                                 ▼
                             [Invoke ApiVaulter: task=fix_usage_apipoint]
                             - Consults PROVIDERSFREEMODELS.md catalog
                             - Selects best matching zero-cost model (Groq / Gemini / OpenRouter)
                             - Returns updated base_url and model identifier to caller
                                 │
                                 ▼
                     [Calling Agent Retries with Free Route: SUCCESS]
```

---

## 3. Dynamic Rerouting & Resolver Recipes

### 3.1 Python Failover Handler (`swarm_sdk/models/failover.py`)
```python
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger("swarm_sdk.vault")

@dataclass(frozen=True)
class FreeModelRoute:
    provider: str
    model_id: str
    base_url: str
    env_key_name: str
    max_context: int

# Canonical zero-cost fallback registry
FREE_TIER_REGISTRY: dict[str, FreeModelRoute] = {
    "coding_fast": FreeModelRoute(
        provider="groq",
        model_id="llama-3.3-70b-versatile",
        base_url="https://api.groq.com/openai/v1",
        env_key_name="GROQ_API_KEY",
        max_context=128000,
    ),
    "coding_expert": FreeModelRoute(
        provider="openrouter",
        model_id="qwen/qwen-2.5-coder-32b-instruct:free",
        base_url="https://openrouter.ai/api/v1",
        env_key_name="OPENROUTER_API_KEY",
        max_context=32768,
    ),
    "reasoning_deep": FreeModelRoute(
        provider="google",
        model_id="gemini-2.0-flash-exp",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        env_key_name="GEMINI_API_KEY",
        max_context=1048576,
    ),
    "reasoning_r1": FreeModelRoute(
        provider="openrouter",
        model_id="deepseek/deepseek-r1:free",
        base_url="https://openrouter.ai/api/v1",
        env_key_name="OPENROUTER_API_KEY",
        max_context=64000,
    ),
}

def resolve_free_fallback_model(
    capability: Literal["coding_fast", "coding_expert", "reasoning_deep", "reasoning_r1"],
) -> FreeModelRoute:
    """Return the optimal zero-cost active route for a given capability."""
    route = FREE_TIER_REGISTRY.get(capability, FREE_TIER_REGISTRY["coding_fast"])
    logger.info("ApiVaulter dynamically rerouted task to zero-cost model: %s on %s", route.model_id, route.provider)
    return route
```

---

## 4. Maintenance & Daily Sync Procedures

1. **Daily Availability Probes**: `ApiVaulter` automatically performs lightweight HTTP 200 health probes on all endpoints listed in this registry before assigning them to active agents.
2. **Quota Tracking**: Once a free tier model returns HTTP 429, `ApiVaulter` temporarily sets a 60-second backoff in memory and shifts traffic to the next provider in the chain (e.g. Groq $\rightarrow$ Google $\rightarrow$ OpenRouter).
3. **Zero-Key Invariant**: Free models requiring standard bearer tokens must still resolve their API keys dynamically from macOS Keychain or 1Password via `swarm_sdk.vault.get()`; keys are never hardcoded.
