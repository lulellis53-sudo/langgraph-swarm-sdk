#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

exec uv run --extra jupyter jupyter lab \
  --ip=127.0.0.1 \
  --port="${JUPYTER_PORT:-8888}" \
  --ServerApp.root_dir="$ROOT/.Jupyter"
