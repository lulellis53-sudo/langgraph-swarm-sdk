---
name: worktree-websearch
description: >-
  Run live web research from the current checkout. Do not create branches or
  worktrees. Use when the user says worktree websearch, /worktree-websearch,
  parallel research, or wants web lookup without extra git isolation.
---

# Worktree Websearch

Research on the public web from the current checkout. Default posture: **read-only on the repo** unless the user asks to save a report.

## 1. Stay on the current checkout

Do **not** create a branch or a new worktree (`git worktree add`, `/worktree`, best-of-n runners). Research from this checkout.

If `WebSearch/` already points at the sibling `worktree/websearch` checkout, use that existing tree. Do not add, remove, or re-point worktrees.

Only create or delete a worktree when the user explicitly asks.

## 2. Clarify the research goal

Before searching:

1. Restate the question and what “done” looks like (facts, comparison, timeline, API behavior, etc.).
2. Note constraints: date range, region, official docs only, no paywalled sources.
3. If the question is about **this repository’s code**, search the repo first; use the web for external libraries, standards, or news.

## 3. Search stack (in order)

1. **Library / API / CLI docs** → Context7 (`resolve-library-id` → `query-docs`).
2. **General web** → Bright Data `search_engine` (or `search_engine_batch` for up to 10 queries).
3. **Fallback** → Tavily `tavily_search`, then `tavily_extract` on the best URLs if snippets are thin.

Do not scrape search-engine result pages with generic scrape tools; use `search_engine`.

## 4. Evidence and output

- Every factual claim gets an inline citation: `[Title](https://full-url)`.
- Prefer primary sources (vendor docs, specs, release notes) over aggregators.
- Cross-check consequential facts with a second source when possible.
- Synthesize; do not dump raw JSON or full page HTML.

Default response shape:

```markdown
## Summary
<2–4 sentences>

## Findings
- <claim> — [Source](url)

## Gaps / caveats
<what could not be verified>

## Suggested next steps (optional)
<only if useful>
```

If the user wants a saved artifact, write it only where they asked (e.g. `research/<slug>.md`) and do not touch unrelated product code.

## 5. Finish

- Leave git state as you found it: no new branch, no new worktree, no worktree remove.
- Commit or merge research notes only when the user asks.

## Hard limits

- No secrets in reports; no exfiltration of private repo content to the web unless the user explicitly requests it.
- No weakening tests or lint to “make research pass.”
- One deliberate search plan; avoid repeating the same query across tools without new evidence.
