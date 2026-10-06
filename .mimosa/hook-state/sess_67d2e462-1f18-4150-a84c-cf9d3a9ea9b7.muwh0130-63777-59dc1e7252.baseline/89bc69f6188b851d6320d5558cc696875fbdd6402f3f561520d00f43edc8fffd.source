#!/usr/bin/env bash
# Cursor worktree bootstrap for LangGraph Swarm SDK (macOS / Linux).
set -euo pipefail

ROOT="${ROOT_WORKTREE_PATH:-}"
if [[ -n "${ROOT}" && -f "${ROOT}/.env" && ! -f .env ]]; then
  cp "${ROOT}/.env" .env
fi

uv sync --extra dev

echo "Worktree setup complete ($(pwd))."
