---
name: worktree-websearch
description: >-
  Run live web research in an isolated Git worktree so installs, scratch notes,
  and experimental edits stay off the main checkout. Use when the user says
  worktree websearch, /worktree-websearch, parallel research, or wants web
  lookup without disturbing their current branch.
---

# Worktree Websearch

Research on the public web from an isolated checkout. Default posture: **read-only on the repo** unless the user asks to save a report.

## 1. Isolate with a worktree

Pick one path:

| Context | Action |
| -------- | ------ |
| IDE chat | Ask the user to send the task as `/worktree <research question>` (or run `/worktree` yourself if the product exposes it in this session). |
| Agent setup missing | Create a sibling worktree manually, then work only inside it: |

```bash
git worktree add ../Swarm-worktree-websearch -b worktree/websearch
```

Open that folder in a second window if the user will keep coding in the main checkout.

The in-repo feature lives at `WebSearch/` (persona + `search.py` contract). Optional `/worktree` is only for isolating installs and scratch notes.

After Cursor creates a worktree, it runs `.cursor/worktrees.json` setup (`uv sync --extra dev`). Wait for setup to finish before heavy commands.

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

If the user wants a saved artifact, write under **`WebSearch/research/<slug>.md`** (gitignored) and do not touch unrelated product code.

## 5. Finish

- **Main checkout unchanged**: leave research commits on `worktree/websearch` or discard the worktree.
- Merge notes into main only when the user asks (`/apply-worktree` in IDE, or cherry-pick / copy the file).
- Remove the worktree when done: `/delete-worktree` or `git worktree remove ../Swarm-worktree-websearch`.

## Hard limits

- No secrets in reports; no exfiltration of private repo content to the web unless the user explicitly requests it.
- No weakening tests or lint to “make research pass.”
- One deliberate search plan; avoid repeating the same query across tools without new evidence.
