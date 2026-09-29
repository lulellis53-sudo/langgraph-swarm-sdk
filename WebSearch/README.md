# WebSearch

In-repo live-web research feature. Use it when the question needs current public sources; use [Researcher](../Agents/Researcher/AGENTS.md) when the answer is in this codebase.

## Search stack (in order)

1. **Library / API / CLI docs** — Context7 (`resolve-library-id` → `query-docs`).
2. **General web** — Bright Data `search_engine` (or `search_engine_batch` for up to 10 queries).
3. **Fallback** — Tavily `tavily_search`, then `tavily_extract` on the best URLs if snippets are thin.

Cursor agents follow [`.cursor/skills/worktree-websearch/SKILL.md`](../.cursor/skills/worktree-websearch/SKILL.md). Optional `/worktree` keeps experimental notes off the main checkout. Saved reports go under `WebSearch/research/` (gitignored).

Python contract: [`search.py`](search.py) names backends and hit types. It does not call the network.
