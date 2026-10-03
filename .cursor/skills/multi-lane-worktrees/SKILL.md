---
name: multi-lane-worktrees
description: >-
  Three fixed git worktrees for parallel agent lanes: WebSearch, Prediction,
  Newsletter. Use when assigning Cursor agents or explaining where lane work
  lives. Do not add other worktrees.
---

# Multi-lane worktrees

| Worktree path | Branch | Lane |
|---------------|--------|------|
| `WebSearch/` (under repo root) | `feature/websearch` | Search/scrape pipeline |
| `../Swarm-Prediction` | `feat/prediction-engine` | `Prediction/` + forecast tests |
| `../Newsletter` | `feat/newsletter` | `Newsletter/` MVP |
| Repo root `Swarm/` | `integration/all-branches` | Merge integration only |

## Setup (once)

```bash
git checkout integration/all-branches
git branch feat/newsletter integration/all-branches   # if missing
git worktree add ../Swarm-Prediction feat/prediction-engine
git worktree add ../Newsletter feat/newsletter
```

WebSearch worktree: `git worktree add WebSearch feature/websearch` from repo root (already present in this project).

## Cursor lane prompts

- [`.cursor/agents/websearch-lane.md`](../agents/websearch-lane.md)
- [`.cursor/agents/prediction-lane.md`](../agents/prediction-lane.md)
- [`.cursor/agents/newsletter-lane.md`](../agents/newsletter-lane.md)

## Rules

- Lane agents edit only their **May edit** paths (see each lane file).
- Only one lane changes root `uv.lock` per integration window.
- Merge order: lane branches → `integration/all-branches` → `main`.
