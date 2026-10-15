# Shared by the launcher and the compose wrapper. Source it; do not execute.
# Secrets live in the macOS Keychain (service "swarm/<NAME>", the swarm_sdk vault convention).
# 1Password is the source of truth: run scripts/sync-secrets to copy missing ones into the Keychain.
# Non-secret settings (URLs, model names, LLM_FIRST) come from WebScraper/config.env.

# Every secret this project uses; only names ever appear here.
WEBSCRAPER_SECRETS=(
  CRAWL4AI_API_TOKEN SEARXNG_SECRET WEBSCRAPER_PG_PASSWORD
  GOOGLE_API_KEY GOOGLE_API_KEY_1 GOOGLE_API_KEY_2
  GROQ_API_KEY GROQ_API_KEY_1 NOVITA_API_KEY NOVITA_API_KEY_1 NOVITA_API_KEY_2 NOVITA_API_KEY_3
  ATLASCLOUD_API_KEY ATLASCLOUD_API_KEY_1 TOKEN_HARBOR_API_KEY TOKEN_HARBOR_API_KEY_1
  ZENMUX_API_KEY ZENMUX_API_KEY_1
  OPENROUTER_API_KEY OPENROUTER_API_KEY_1
  MISTRAL_API_KEY MISTRAL_API_KEY_1 COHERE_API_KEY COHERE_API_KEY_1 OLLAMA_CLOUD_API_KEY
  NVIDIA_NIM_API_KEY NVIDIA_NIM_API_KEY_1 STEPFUN_API_KEY
  FIREWORKS_API_KEY POOLSIDE_API_KEY POOLSIDE_API_KEY_1 MINIMAX_API_KEY
  ZAI_API_KEY KIMI_API_KEY KIMI_API_KEY_1 KIMI_API_KEY_2 MIMO_API_KEY XAI_API_KEY
)

# load_secrets NAME...: export each unset variable from the Keychain (silent when absent).
load_secrets() {
  local name val
  for name in "$@"; do
    [ -n "${(P)name}" ] && continue
    val=$(/usr/bin/security find-generic-password -s "swarm/$name" -w 2>/dev/null || true)
    [ -n "$val" ] && export "$name=$val"
  done
}

# load_config FILE: export KEY=VALUE lines of a non-secret config file (existing env wins).
load_config() {
  local file="$1" line key val
  [ -f "$file" ] || return 0
  while IFS= read -r line; do
    [[ "$line" =~ '^[[:space:]]*([A-Z][A-Z0-9_]*)=(.*)$' ]] || continue
    key="${match[1]}"; val="${match[2]}"; val="${val%\"}"; val="${val#\"}"
    [ -z "${(P)key}" ] && export "$key=$val"
  done < "$file"
}
