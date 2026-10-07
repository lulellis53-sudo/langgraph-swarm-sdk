# Contributing

Use [uv](https://docs.astral.sh/uv/) and Python `>=3.14.5`. Read [AGENTS.md](AGENTS.md) before changing the SDK or `Agents/` personas.

## Setup

```bash
uv sync --extra dev
```

Add extras only when the change needs them (`faiss`, `mem0`, `observability`, `opencl`, …).

## Quality gate

Run before opening a pull request:

```bash
uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 pytest Agents/benchmark -q
uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 ruff check src Agents/benchmark Main
uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 ty check src Agents/benchmark Main
uv run python -m swarm_sdk.agents.validate
```

Do not weaken Ruff, ty, or tests to get a green result.

## Scope

- Smallest correct diff. Match existing naming and Ruff (`line-length = 100`).
- New modules under `src/swarm_sdk/`, `Agents/benchmark/`, or `Main/`: copy the lite or full scaffold in `.cursor/templates/`. First import after the docstring must be `from __future__ import annotations`.
- Edit `src/swarm_sdk/pb/swarm.proto`, then `uv run python -m swarm_sdk.pb`. Do not hand-edit `swarm_pb2*` stubs.
- YAML may name env vars (`api_key_env`). Never commit `.env`, keys, or secret values.

## Git

- Target `main` (or the lane branch you were asked to use). Do not force-push `main`.
- Do not add extra git worktrees. The fixed lanes are documented in [`.cursor/skills/multi-lane-worktrees/SKILL.md`](.cursor/skills/multi-lane-worktrees/SKILL.md).

## Security reports

See [SECURITY.md](SECURITY.md). Do not file secret leaks as public issues.
