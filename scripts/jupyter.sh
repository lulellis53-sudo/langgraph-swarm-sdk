#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

exec uv run --extra jupyter jupyter lab --notebook-dir "$ROOT/notebooks" "$@"
