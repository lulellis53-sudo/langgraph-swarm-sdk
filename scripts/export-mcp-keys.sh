#!/bin/zsh
# Export MCP API keys from the macOS Keychain into the current shell.
# Usage:  source scripts/export-mcp-keys.sh
# Then:   claude
# Never prints secret values.
set -uo pipefail

_swarm_export_key() {
  local env_name="$1"
  shift
  local svc val=""
  if [[ -n "${(P)env_name:-}" ]]; then
    return 0
  fi
  for svc in "$@"; do
    val=$(/usr/bin/security find-generic-password -s "$svc" -w 2>/dev/null || true)
    if [[ -z "$val" ]]; then
      val=$(/usr/bin/security find-generic-password -a "$svc" -w 2>/dev/null || true)
    fi
    if [[ -n "$val" ]]; then
      export "$env_name=$val"
      print -u2 -- "$env_name: exported from keychain ($svc)"
      return 0
    fi
  done
  print -u2 -- "$env_name: missing (store with: uv run swarm-vault set $env_name)"
  return 1
}

_swarm_export_key CONTEXT7_API_KEY swarm/CONTEXT7_API_KEY CONTEXT7_API_KEY
_swarm_export_key CONTEXT_DEV_API_KEY swarm/CONTEXT_DEV_API_KEY CONTEXT_DEV_API_KEY
# Apify MCP expects APIFY_TOKEN; Keychain may still use swarm/APIFY_API_KEY.
_swarm_export_key APIFY_TOKEN swarm/APIFY_TOKEN APIFY_TOKEN swarm/APIFY_API_KEY APIFY_API_KEY
_swarm_export_key BRIGHT_DATA_API_TOKEN \
  swarm/BRIGHT_DATA_API_TOKEN BRIGHT_DATA_API_TOKEN BRIGHTDATA_API_KEY
_swarm_export_key APPWRITE_API_KEY swarm/APPWRITE_API_KEY APPWRITE_API_KEY
_swarm_export_key APPWRITE_PROJECT_ID swarm/APPWRITE_PROJECT_ID APPWRITE_PROJECT_ID
_swarm_export_key APPWRITE_ENDPOINT swarm/APPWRITE_ENDPOINT APPWRITE_ENDPOINT

# Optional Bright Data zones (free-tier tools work without these).
if ! _swarm_export_key BRIGHT_DATA_UNLOCKER_ZONE \
  swarm/BRIGHT_DATA_UNLOCKER_ZONE BRIGHT_DATA_UNLOCKER_ZONE 2>/dev/null; then
  print -u2 -- "BRIGHT_DATA_UNLOCKER_ZONE: optional (unset)"
fi
if ! _swarm_export_key BRIGHT_DATA_BROWSER_ZONE \
  swarm/BRIGHT_DATA_BROWSER_ZONE BRIGHT_DATA_BROWSER_ZONE 2>/dev/null; then
  print -u2 -- "BRIGHT_DATA_BROWSER_ZONE: optional (unset)"
fi

unset -f _swarm_export_key
