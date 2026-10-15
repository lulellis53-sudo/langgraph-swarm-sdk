# Source this in a git worktree to reuse the repo single uv environment:
#   source scripts/dev-env.sh && uv run --no-sync pytest -q
# --no-sync stops uv from re-pointing the editable swarm_sdk install at this worktree.
export UV_PROJECT_ENVIRONMENT="$HOME/Myworkspace/Swarm/.venv"
unset UV_PYTHON
