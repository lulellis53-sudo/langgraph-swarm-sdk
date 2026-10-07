# /worktree-websearch

Live web research from an isolated **sibling** git worktree. The Hatch package
`WebSearch/` stays in this checkout. Product patches are **CodeFixer**, not this
command.

## Cursor IDE

1. Open **Agent** chat (Agent mode).
2. Type **`/worktree-websearch`** plus the research question.
3. If the answer implies code changes, run **`/code-fixer`** (or `@code-fixer`)
   with the findings and claimed paths (`WebSearch/`, `tests/`).

## What it does

1. Treats `WebSearch/` as the Python package (`frontend/`, `midend/`,
   `backend/`, `providers.yaml`) — never a nested worktree or symlink target.
2. Optional sibling tree: `git worktree add ../Swarm-WebSearch worktree/websearch`
   for scratch only.
3. Search: Context7 → Bright Data `search_engine` → Tavily.
4. Returns a cited report. Does **not** weaken tests or edit product code.

Skill: [`.cursor/skills/worktree-websearch/SKILL.md`](../skills/worktree-websearch/SKILL.md).
CodeFixer: [`.cursor/commands/code-fixer.md`](code-fixer.md).
