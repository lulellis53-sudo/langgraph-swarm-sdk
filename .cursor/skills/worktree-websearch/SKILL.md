---
name: worktree-websearch
description: >-
  Live web research from an isolated sibling git worktree; Hatch package
  WebSearch/ stays put. Use when the user says worktree websearch,
  /worktree-websearch, parallel research, or wants lookup without disturbing
  the current branch. Product patches go to /code-fixer, not this skill.
---

# Worktree Websearch

Research on the public web from an isolated **sibling** checkout. Default
posture: **read-only on the product tree** unless the user asks to save a
report. **CodeFixer** (`/code-fixer`, `@code-fixer`) owns patches to the Hatch
package and tests.

## Package vs research worktree

`WebSearch/` in this repository is a **Hatch Python package**
(`packages = ["src/swarm_sdk", "WebSearch"]`). Pipeline code is
`WebSearch/frontend/`, `WebSearch/midend/`, `WebSearch/backend/`, plus
`WebSearch/providers.yaml`. Do **not** `git worktree add` inside `WebSearch/`,
do **not** `ln -s` a nested checkout over that folder, and do **not** treat
the package directory as a git worktree.

A **sibling** git worktree named `Swarm-WebSearch` is only for isolated
research (scratch notes, extra installs). It is not the Python package path.

## Multipath

```text
+==========================================================+
| /worktree-websearch  (research) → optional CodeFixer     |
+==========================================================+
        |
        v
 STAGE 0  Goal + constraints (repo vs live web)
        |
        +-- this repo's WebSearch/ code? -- yes --> search tree first
        |                                              |
        |                    review/findings to patch? -- yes --> PATH C CodeFixer
        |                                              |
        +-- live web / library docs ----------------> PATH A Context7
                                                      PATH B Bright Data / Tavily
        |
        v
 STAGE 1  Cited report (sibling tree only if saving)
        |
        v
 STAGE 2  Finish: no nested worktree; no product edit from this skill
```

| Path | When | Who writes |
| ---- | ---- | ---------- |
| **A** | Library / CLI / API doubt | Context7; no product patch |
| **B** | General web facts | Bright Data `search_engine`, then Tavily |
| **C** | Reviewer findings or “fix WebSearch” | **CodeFixer** on claimed `WebSearch/**`, `tests/**` |

Never apply product patches from the research worktree. Hand off to
[`.cursor/agents/code-fixer.md`](../../agents/code-fixer.md) /
[`/code-fixer`](../../commands/code-fixer.md). Contract:
`Agents/CodeFixer/AGENTS.md` (parent Swarm).

## 1. Isolate with a worktree (research only)

Pick one path:

| Context | Action |
| -------- | -------- |
| IDE chat | `/worktree-websearch <question>` or `/worktree <question>` if the product exposes it |
| Agent setup missing | Create a **sibling** worktree, then work only inside it |

```bash
git worktree add ../Swarm-WebSearch worktree/websearch
```

Do not nest that worktree under `WebSearch/` and do not replace `WebSearch/`
with a symlink. Do not create extra branches outside the fixed agent lanes
unless the user explicitly asked for this research tree.

Open that sibling folder in a second window if the user will keep coding in
the main checkout.

After Cursor creates a worktree, it runs `.cursor/worktrees.json` setup
(`uv sync --extra dev`). Wait for setup to finish before heavy commands.

## 2. Clarify the research goal

Before searching:

1. Restate the question and what “done” looks like (facts, comparison, timeline, API behavior, etc.).
2. Note constraints: date range, region, official docs only, no paywalled sources.
3. If the question is about **this repository’s code**, search the repo first; use the web for external libraries, standards, or news.
4. If the user wants **code changed**, stop research and invoke **CodeFixer** (Path C).

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

## CodeFixer (only if product code must change)
<finding → claimed path; then /code-fixer>

## Suggested next steps (optional)
<only if useful>
```

If the user wants a saved artifact, write under the **sibling research
worktree** only, e.g. `research/<slug>.md`, and do not touch unrelated product
code.

## 5. Finish

- **Main checkout unchanged** by this skill: leave research commits on
  `worktree/websearch` or discard the sibling worktree.
- Merge notes into main only when the user asks (`/apply-worktree` in IDE, or
  cherry-pick / copy the file).
- Product diffs: CodeFixer only; no commit unless the user asks.
- Remove the worktree when done: `/delete-worktree` or
  `git worktree remove ../Swarm-WebSearch`.

## Pre / post checklist

- [ ] Package `WebSearch/` not treated as a git worktree
- [ ] Context7 first for library/CLI doubt
- [ ] Citations on factual claims
- [ ] Product edits delegated to `/code-fixer` (or none)
- [ ] No secrets in reports

## Hard limits

- No secrets in reports; no exfiltration of private repo content to the web unless the user explicitly requests it.
- No weakening tests or lint to “make research pass.”
- One deliberate search plan; avoid repeating the same query across tools without new evidence.
- No nested `git worktree add` / `ln -s` over `WebSearch/`.
- No CodeFixer-style patches from this skill (disjoint role).
