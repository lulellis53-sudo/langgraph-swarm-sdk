# Vault + mem0 cache for WebSearch agents — design

Date: 2026-10-01 | Status: draft, awaiting review

## Goal
Agents that call `WebSearch/agent_tools.search_brief` can recall and save search briefs through
mem0 (cache). API keys live in a vault outside the repo; a fresh checkout starts from a
reference-only template. No secret value is ever in the repo, logs, exceptions or chat.

## Decisions (from brainstorming)
- mem0 role: cache and recall of briefs (query -> brief).
- Database scope: memory stores only (`src/swarm_sdk/memory/`); no backend deleted.
- Vault: 1Password (`op`) primary, macOS Keychain (`security`) fallback.
- Not in scope: other memory backends, `core/swarm.py` / orchestrator SQLite state, zsh files.

## Components
1. `src/swarm_sdk/vault.py`
   - `get(name) -> str | None`: provider chain, first hit wins:
     process env -> `op read` -> Keychain (`security find-generic-password -s swarm/<name> -w`)
     -> `~/.env` (legacy, logs a one-line migrate warning without the value).
   - `load_into_env(names)`: sets `os.environ` for names not already set.
   - Providers are optional; a missing CLI or item is a miss, not an error. `subprocess` with
     timeout, no shell, stdout never logged; exceptions carry the name only.
   - CLI `swarm-vault set NAME` (hidden `getpass` -> Keychain), `swarm-vault list` (names only).
2. `.env.tpl` (repo root, committed): `NAME=op://Swarm/<item>/credential` references only.
   Run: `op run --env-file=.env.tpl -- uv run swarm-api`. Real `.env` stays gitignored.
3. Entry points (`swarm-api`, `swarm-grpc`, benchmark runner) call `load_into_env` once with
   names taken from the `*_env` fields in `swarm.yaml` / `providers.yaml`.
4. Memory interface: add `get(key) -> str | None` and `put(key, value)` to `memory/base.py`,
   implemented by `Mem0Store`. `search` unchanged.
5. `WebSearch/agent_tools.search_brief(..., cache=None)`: key = hash(normalized query +
   provider spec). Hit -> return saved brief; miss -> search, then save. mem0 or key missing ->
   search as before, no failure. `WebSearch/` stays standalone (no `swarm_sdk` import); the
   cache is injected by the caller.

## Error handling
Vault misses degrade to the next provider; `get` returns None if all miss. Cache errors are
caught at the boundary, logged once without payloads, and never fail a search.

## Testing
- Vault: injected fake runner (no real Keychain/`op`); missing item, non-zero exit, timeout,
  provider order, env precedence, no secret in logs/exceptions.
- Cache: hit, miss, mem0 unavailable, key stability across query normalization.
- Gate: project quality gate from AGENTS.md.

## Open items
- `op` sign-in state and the 1Password vault/item names are unverified (not run).
- `Mem0Store` hosted-API `get` by key may need a metadata-filter search; confirm against the
  installed mem0 client during planning.
