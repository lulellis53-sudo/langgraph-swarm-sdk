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
| `~/Myworkspace/Swarm/` | `integration/myworkspace-2026-10` → `main` | SDK integration + coordination |
| `~/Myworkspace/Swarm-Prediction/` | `lane/prediction` (based on `lane/websearch`) | `Prediction/` + forecast engine, synced from websearch |
| `~/Myworkspace/Swarm/WebSearch/` | `lane/websearch` | `WebSearch/` search/scrape pipeline |
| `~/Myworkspace/BotDeal/` | `feat/botdeal` | `Prediction/BotDeal/` + PromoDeals (no separate lane yet) |
| `~/Myworkspace/Newsletter/` | `feat/newsletter` | `Newsletter/` MVP (no separate lane yet) |

**Primary lanes:**
- `lane/sdk` — `src/swarm_sdk/`, `tests/`, `pyproject.toml`
- `lane/agents` — `Agents/`
- `lane/websearch` — `WebSearch/`
- `lane/prediction` — `Prediction/`, follows `lane/websearch` |

## Setup (once)

From repo root, keep **one branch per worktree** (Git refuses the same branch in two trees unless `--force`).

```bash
git checkout main
git branch feat/newsletter main   # if missing
git worktree add ../Swarm-Prediction feat/prediction-engine
git worktree add ../Newsletter feat/newsletter
git worktree add ../BotDeal feat/botdeal   # or ./Prediction/BotDeal/sync_worktree.sh
git worktree list
```

Existing branch on a new path (official form: `git worktree add <path> <branch>`):

- [git-worktree(1)](https://git-scm.com/docs/git-worktree)

WebSearch worktree (already present):

```bash
git worktree add WebSearch feature/websearch
```

## Quality gates (uv)

Project options go **before** the subcommand; repeat `--extra` for each optional group:

```bash
uv run --extra forecast pytest tests/test_prediction_engine.py -q
uv lock
```

- [uv CLI reference](https://docs.astral.sh/uv/reference/cli/) (`--extra`, `uv run`, `uv lock`)

## Cursor lane prompts

- [`.cursor/agents/websearch-lane.md`](../agents/websearch-lane.md)
- [`.cursor/agents/prediction-lane.md`](../agents/prediction-lane.md)
- [`.cursor/agents/newsletter-lane.md`](../agents/newsletter-lane.md)

## Swarm persona

Lane audits and integration planning: [`Agents/Worktree/AGENTS.md`](../../Agents/Worktree/AGENTS.md)
(`lane_audit`, `integration_window_check`).

## Branch authorization

- **Do not create branches.** Only these branches may exist:
  - `main` (stable)
  - `integration/myworkspace-2026-10` (pre-release)
  - `lane/sdk`, `lane/agents`, `lane/websearch`, `lane/prediction` (parallel work)
- Creating any other branch triggers CI failure. CI checks for unauthorized branches on every push.
- Temporary feature branches (`feat/*`, `feature/*`, `fix/*`) must be explicitly authorized by the user. Ask first.

## Rules

- Lane agents edit only their **May edit** paths (see each lane file).
- Only one lane changes root `uv.lock` per integration window.
- Merge order: lane branches → `main` (or `integration/myworkspace-2026-10` then `main`).
- **Never commit to a lane or protected branch unless the user asks.** Work only on temporary feature branches.
