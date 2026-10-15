# ApiVaulter Skill: Secrets Detection, Vaulting & Code Wrapper Injection

> **Scope**: High-performance detection of raw secrets via CLI (`rg`, `fd`), folder monitoring via `zoxide`, secure vaulting into 1Password & macOS Keychain, non-destructive model endpoint probing, and zero-leak code wrapper refactoring.

---

## 1. High-Performance Secret Detection via Modern CLI (`rg`)

Scan directories without checking binaries, caches, or `.git` directories. Bounded line outputs prevent log bloat:

```bash
# 1. Broad secret scan across current worktree with ripgrep:
rg -n -m 5 --no-heading --hidden -g '!.git' -g '!node_modules' -g '!.venv' \
  -e '(?:sk-[a-zA-Z0-9_\-]{32,})' \
  -e '(?:sk-ant-[a-zA-Z0-9_\-]{32,})' \
  -e '(?:AIza[0-9A-Za-z\-_]{35})' \
  -e '(?:ghp_[a-zA-Z0-9]{36}|github_pat_[a-zA-Z0-9_]{82})' \
  -e '(?:tvly-[a-zA-Z0-9_\-]{32,})' \
  -e '(?:exa-[a-zA-Z0-9_\-]{32,})' \
  -e '(?:gsk_[a-zA-Z0-9]{50,})' \
  -e '(?:(?:api_key|apikey|secret|token|auth_token)\s*=\s*["'\''"][a-zA-Z0-9_\-\.]{16,}["'\''"])'

# 2. Targeted search for accidental .env files across worktrees:
fd -H '(^|\.)env(\..+)?$' -E '.venv' -E 'node_modules' /Users/usuario/Myworkspace
```

### Secret Token Pattern Signatures
| Provider | Target Token Signature Regex | Canonical Vault Name |
| :--- | :--- | :--- |
| **OpenAI** | `sk-(?:proj-)?[a-zA-Z0-9_\-]{32,}` | `OPENAI_API_KEY` |
| **Anthropic** | `sk-ant-[a-zA-Z0-9_\-]{32,}` | `ANTHROPIC_API_KEY` |
| **Google Gemini** | `AIza[0-9A-Za-z\-_]{35}` | `GEMINI_API_KEY` |
| **Groq** | `gsk_[a-zA-Z0-9]{50,}` | `GROQ_API_KEY` |
| **Tavily** | `tvly-[a-zA-Z0-9_\-]{32,}` | `TAVILY_API_KEY` |
| **Exa** | `exa-[a-zA-Z0-9_\-]{32,}` | `EXA_API_KEY` |
| **Jina AI** | `jina_[a-zA-Z0-9_\-]{32,}` | `JINA_API_KEY` |
| **Brave Search** | `BSAY[a-zA-Z0-9_\-]{28,}` | `BRAVE_API_KEY` |
| **Apify** | `apify_api_[a-zA-Z0-9]{32,}` | `APIFY_TOKEN` |
| **You.com** | `ydc_[a-zA-Z0-9_\-]{32,}` | `YDC_API_KEY` |
| **Bright Data** | `brd_customer_[a-zA-Z0-9_\-]{24,}` | `BRIGHT_DATA_API_TOKEN` |
| **ParallelAI** | `parallel_[a-zA-Z0-9_\-]{28,}` | `PARALLEL_API_KEY` |
| **HuggingFace** | `hf_[a-zA-Z0-9]{34,}` | `HF_TOKEN` |
| **GitHub** | `ghp_[a-zA-Z0-9]{36}` / `github_pat_[a-zA-Z0-9_]{82}` | `GITHUB_TOKEN` |

---

## 2. Workspace Navigation & Folder Monitoring (`zoxide`)

Use `zoxide` to rapidly jump between worktree lanes and monitor tracked project roots:

```bash
# Query known project worktree lanes:
zoxide query Swarm
zoxide query Agents
zoxide query WebSearch

# Execute bounded scanning in the resolved path:
TARGET_DIR="$(zoxide query WebSearch)"
rg -n -m 3 --hidden -g '!.git' 'sk-[a-zA-Z0-9]' "$TARGET_DIR"
```

---

## 3. Secure Multi-Backend Vaulting

### 3.1 macOS Keychain Storage (`security`)
Values are piped via stdin to prevent plaintext keys appearing in shell history (`~/.zsh_history`) or process listings (`ps -ef`):

```bash
# Store or update secret in macOS Keychain under service "swarm/<NAME>":
printf 'add-generic-password -a "%s" -s "swarm/%s" -w "%s" -U\n' "$USER" "$KEY_NAME" "$KEY_VALUE" | security -i

# Verify key existence without printing the value:
security find-generic-password -s "swarm/$KEY_NAME" >/dev/null 2>&1 && echo "Vaulted in Keychain: OK"
```

### 3.2 1Password Storage (`op` CLI)
Store credentials into 1Password vault with zero stdout exposure:

```bash
# Create or update an API Credential item in 1Password:
op item create --category "API Credential" \
  --title "swarm/$KEY_NAME" \
  --vault "Private" \
  "credential=$KEY_VALUE" >/dev/null 2>&1

# Verify item existence in 1Password:
op item get "swarm/$KEY_NAME" --fields id >/dev/null 2>&1 && echo "Vaulted in 1Password: OK"
```

---

## 4. Live Model & Endpoint Verification Probes

Before vaulting a key and refactoring code, run a non-destructive HTTP status probe to ensure the token is valid and active:

```bash
# 1. OpenAI Probe:
curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $KEY_VALUE" https://api.openai.com/v1/models

# 2. Anthropic Probe:
curl -s -o /dev/null -w "%{http_code}" -H "x-api-key: $KEY_VALUE" -H "anthropic-version: 2023-06-01" https://api.anthropic.com/v1/models

# 3. Google Gemini Probe:
curl -s -o /dev/null -w "%{http_code}" "https://generativelanguage.googleapis.com/v1beta/models?key=$KEY_VALUE"

# 4. Groq Probe:
curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $KEY_VALUE" https://api.groq.com/openai/v1/models

# 5. Tavily Search Probe:
curl -s -o /dev/null -w "%{http_code}" -H "Content-Type: application/json" -d "{\"api_key\": \"$KEY_VALUE\", \"query\": \"ping\"}" https://api.tavily.com/search

# Expected outcome: HTTP 200 (Success)
```

---

## 5. In-Code Wrapper Injection (Zero-Leak Refactor)

Replace the hardcoded secret string in code with dynamic retrieval wrappers:

### 5.1 Python Replacement Pattern
```python
# -------------------- BEFORE (INSECURE) --------------------
# OPENAI_API_KEY = "sk-proj-***...***"
# client = OpenAI(api_key="sk-proj-***...***")

# -------------------- AFTER (VAULT-WRAPPED) ----------------
import os
from swarm_sdk.vault import get as get_vault_key

# 1. Direct retrieval via swarm_sdk.vault:
OPENAI_API_KEY = get_vault_key("OPENAI_API_KEY")

# 2. Or fallback resolution (env -> Keychain -> 1Password):
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY") or get_vault_key("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)
```

### 5.2 TypeScript / Node.js Replacement Pattern
```typescript
// -------------------- BEFORE (INSECURE) --------------------
// const apiKey = "sk-ant-api03-***...***";

// -------------------- AFTER (VAULT-WRAPPED) ----------------
import { execSync } from 'child_process';

function getVaultKey(name: string): string {
  if (process.env[name]) return process.env[name]!;
  try {
    return execSync(`security find-generic-password -s "swarm/${name}" -w`, { encoding: 'utf-8', stdio: ['pipe', 'pipe', 'ignore'] }).trim();
  } catch {
    return '';
  }
}

const apiKey = getVaultKey("ANTHROPIC_API_KEY");
```

### 5.3 Safe In-Place Replacement using `sd`
```bash
# In-place replace hardcoded key pattern with vault accessor:
sd 'OPENAI_API_KEY\s*=\s*["'\''"][^"'\''"]+["'\''"]' 'OPENAI_API_KEY = get_vault_key("OPENAI_API_KEY")' path/to/file.py
```

---

## 6. Inter-Agent API Remediation & Daily Free Models Routing

### 6.1 `fix_api_key`: Autonomous Secret Rotation Pipeline
When a caller provides a failed provider name and error code:
```bash
# 1. Check for fallback key in macOS Keychain:
FALLBACK_KEY=$(security find-generic-password -s "swarm/${PROVIDER}_BACKUP" -w 2>/dev/null)

# 2. Or query 1Password for secondary active key:
if [ -z "$FALLBACK_KEY" ]; then
  FALLBACK_KEY=$(op item get "swarm/${PROVIDER}" --fields credential 2>/dev/null)
fi

# 3. Verify fallback key with lightweight health probe:
PROBE_CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $FALLBACK_KEY" "$HEALTH_ENDPOINT")
if [ "$PROBE_CODE" = "200" ]; then
  # Arm the Keychain primary entry with the working key:
  printf 'add-generic-password -a "%s" -s "swarm/%s" -w "%s" -U\n' "$USER" "$PROVIDER" "$FALLBACK_KEY" | security -i
fi
```

### 6.2 `search_provider_free_models`: Reading Free Models & Multi-Tier Registries
Callers query the active daily zero-cost catalog at `Agents/ApiVaulter/docs/PROVIDERSFREEMODELS.md` or the complete account tier registry at `Agents/ApiVaulter/docs/PROVIDERS_REGISTRY.md`:
```python
from pathlib import Path

def get_free_models_catalog() -> str:
    catalog_path = Path(__file__).resolve().parent.parent / "docs" / "PROVIDERSFREEMODELS.md"
    return catalog_path.read_text(encoding="utf-8")

def get_providers_registry() -> str:
    registry_path = Path(__file__).resolve().parent.parent / "docs" / "PROVIDERS_REGISTRY.md"
    return registry_path.read_text(encoding="utf-8")

def get_websearchers_registry() -> str:
    registry_path = Path(__file__).resolve().parent.parent / "docs" / "WEBSEARCHERS.md"
    return registry_path.read_text(encoding="utf-8")

def get_memory_identity_registry() -> str:
    registry_path = Path(__file__).resolve().parent.parent / "docs" / "MEMORY_AND_IDENTITY.md"
    return registry_path.read_text(encoding="utf-8")
```

### 6.3 `fix_usage_apipoint`: Multi-Tier Dynamic 429 Failover Route
When HTTP 429 (Rate Limit Exhaustion) is intercepted, redirect traffic along the multi-tier fallback chain defined in `PROVIDERS_REGISTRY.md`:
`Tier 1 (Pro)` -> `Tier 2 (Cerebras/SambaNova)` -> `OpenRouter ($10 Paid)` -> `Tier 4 (Daily Free / Groq)`:

```python
def get_rate_limit_fallback(failing_provider: str, task_criticality: str = "normal") -> dict[str, str]:
    # 1. High-criticality tasks fail over to Tier 2 Hardware Accelerators:
    if task_criticality == "high":
        return {
            "tier": "Tier 2 (Hardware Accelerator)",
            "provider": "cerebras",
            "model": "llama3.1-70b",
            "base_url": "https://api.cerebras.ai/v1",
            "env_key": "CEREBRAS_API_KEY",
            "throughput": "1500 tok/s"
        }
    
    # 2. General tasks fail over to OpenRouter $10 Paid balance (high RPM):
    if failing_provider in ("openai", "anthropic"):
        return {
            "tier": "Tier 1 (Paid Fallback)",
            "provider": "openrouter",
            "model": "meta-llama/llama-3.3-70b-instruct",
            "base_url": "https://openrouter.ai/api/v1",
            "env_key": "OPENROUTER_API_KEY",
            "rpm_status": "high_priority"
        }
    
    # 3. Standard / background tasks fail over to Tier 4 Zero-Cost Groq or Gemini Free:
    return {
        "tier": "Tier 4 (Zero-Cost Free Tier)",
        "provider": "groq",
        "model": "llama-3.3-70b-versatile",
        "base_url": "https://api.groq.com/openai/v1",
        "env_key": "GROQ_API_KEY",
        "quota": "14400 RPD free"
    }
```
