---
name: multi-lane-worktrees
description: >-
  Use when assigning a Cursor agent to WebSearch, Prediction, or Newsletter,
  when a prompt asks for a new git worktree or branch, or when explaining
  where lane work lives. Do not add, remove, or re-point worktrees.
---

# Multi-lane worktrees

Four checkouts. One branch per tree. Stay on the assigned path.

| Lane | Path | Branch | Prompt | Gate |
|------|------|--------|--------|------|
| Integration | `Swarm/` (repo root) | `integration/all-branches` | (this tree) | root quality gate in `AGENTS.md` |
| WebSearch | `WebSearch/` | `feature/websearch` | [websearch-lane.md](../../agents/websearch-lane.md) | `cd WebSearch && uv run pytest tests -q` |
| Prediction | `../Swarm-Prediction` | `feat/prediction-engine` | [prediction-lane.md](../../agents/prediction-lane.md) | `uv run --extra forecast pytest tests/test_prediction_engine.py -q` |
| Newsletter | `../Newsletter` | `feat/newsletter` | [newsletter-lane.md](../../agents/newsletter-lane.md) | `uv run pytest tests/test_newsletter_engine.py -q` |

Editor layout: [codeworkspace/swarm.code-workspace](../../../codeworkspace/swarm.code-workspace).

**May edit (one line):** Integration owns `src/swarm_sdk/` and coordination. WebSearch owns `WebSearch/**`. Prediction owns `Prediction/**` + `tests/test_prediction_engine.py`. Newsletter owns `Newsletter/**` + `tests/test_newsletter*.py`. Full lists live in the lane prompts.

## Rules

- Do not `git worktree add`, `git worktree remove`, `git checkout -b`, or best-of-n isolated trees.
- Git allows one branch in only one worktree unless `--force`. Never `--force`.
- Only one lane changes root `uv.lock` in a given integration window.
- Merge: lane branches → `integration/all-branches` → `main`.
- `worktree-websearch` is live research from the current checkout, not a fourth product lane.

## Setup (once, only if a listed tree is missing)

Official form is `git worktree add <path> <branch>` ([git-worktree(1)](https://git-scm.com/docs/git-worktree)).

```bash
git worktree list
# only if a row above is absent:
git worktree add WebSearch feature/websearch
git worktree add ../Swarm-Prediction feat/prediction-engine
git worktree add ../Newsletter feat/newsletter
```

Create a missing branch from `integration/all-branches` first (`git branch feat/newsletter integration/all-branches`). Do not `git checkout` the root onto a lane branch.

## Quality gates (uv)

Project options go **before** the subcommand; repeat `--extra` for each group ([uv CLI](https://docs.astral.sh/uv/reference/cli/)).

```bash
uv run --extra forecast pytest tests/test_prediction_engine.py -q
```
