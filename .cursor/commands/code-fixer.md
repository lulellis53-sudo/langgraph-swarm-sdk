# /code-fixer

Apply Reviewer / code-reviewer findings with the Cursor **code-fixer** subagent.

## Cursor IDE

1. Open **Agent** chat (Agent mode).
2. Attach the review or files (`@WebSearch`, `@code-reviewer` output).
3. Run **`/code-fixer`** or mention **`@code-fixer`**.

## What it does

1. Uses the latest review in this chat (verdict, findings table, coverage_gaps).
2. Fixes **critical** and **major** first; **minor** if cheap; skips **nit** unless asked.
3. Smallest diffs. **Must** prove with all of:
   - `uv run --extra dev ruff check <claimed Python>`
   - `uv run --extra dev ty check <claimed Python>`
   - `uv run pytest <touched tests> -q`
   - `uv run python -m swarm_sdk.agents.validate` when agent manifests changed
   Pytest alone is not done. Do not commit unless asked.

See [`.cursor/agents/code-fixer.md`](../agents/code-fixer.md) and [Cursor subagents](https://cursor.com/docs/subagents).

Research (`/worktree-websearch`) does not patch `WebSearch/`; send findings here.
