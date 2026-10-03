# Cursor lane: Newsletter

You work in the **Newsletter worktree** (`../Newsletter` on branch `feat/newsletter`).

## Modus operandi

Think → Check (read `Newsletter/` package and tests) → analyse → write → **Context7** for any mail/markdown library CLI you add → tighten → re-check.

## May edit

- `Newsletter/**`
- `tests/test_newsletter*.py` on this branch
- Optional `Agents/Newsletter/` manifest when orchestrator should assign `newsletter_mvp`
- Root `pyproject.toml` optional `newsletter` extra + `uv.lock` **only on `feat/newsletter`**

## Do not edit

- `WebSearch/**`, `Prediction/**`
- `Main/config/model_registry.yaml`, `src/swarm_sdk/models/` unless user asks on main
- Email/SMTP credentials in repo (env var names only in YAML if needed later)

## Quality gate

```bash
cd ../Newsletter && uv run pytest tests/test_newsletter_engine.py -q
```

## Git

Stay on `feat/newsletter`. Do not create branches or worktrees. See [`.cursor/rules/git-docs.mdc`](../rules/git-docs.mdc).
