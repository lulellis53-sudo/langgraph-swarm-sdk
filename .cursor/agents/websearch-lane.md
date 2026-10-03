# Cursor lane: WebSearch

You work only in the **WebSearch worktree** (`WebSearch/` on branch `feature/websearch`).

## Modus operandi

Think → Check (read callers, tests, `providers.yaml`) → analyse → write → **Context7** for any CLI/library you touch → tighten → re-check.

## May edit

- `WebSearch/frontend/`, `WebSearch/midend/`, `WebSearch/backend/`
- `WebSearch/tests/`, `WebSearch/providers.yaml`, `WebSearch/PIPELINE.md`
- WebSearch-local `Agents/` personas and benchmarks under `WebSearch/Agents/benchmark/`
- `WebSearch/pyproject.toml` and `WebSearch/uv.lock` **inside this worktree only**

## Do not edit

- Root `Prediction/`, `Newsletter/`, `../Swarm-Prediction`, `../Newsletter`
- Root `Agents/coordination.yaml` unless explicitly integrating
- Broad refactors under root `src/swarm_sdk/` (integration lane owns SDK merges)

## Quality gate

```bash
cd WebSearch && uv run pytest tests -q
```

Add targeted benchmark paths when you touch harness code.

## Git

Stay on `feature/websearch`. Do not create branches or worktrees. See [`.cursor/rules/git-docs.mdc`](../rules/git-docs.mdc).
