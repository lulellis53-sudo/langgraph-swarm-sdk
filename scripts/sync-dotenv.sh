#!/usr/bin/env bash
# Canonical dotenv lives only on the main Swarm worktree. Other git worktrees
# get relative symlinks so Python/VS Code keep seeing `.env` at the repo root.
# Usage:  bash scripts/sync-dotenv.sh
# Never prints secret values. Does not copy a real .env onto another branch.
set -euo pipefail

MAIN="${SWARM_MAIN:-$HOME/Myworkspace/Swarm}"
DOTENV_DIR="${MAIN}/dotenv"

if [[ ! -d "${MAIN}/.git" && ! -f "${MAIN}/.git" ]]; then
  echo "error: main worktree not found: ${MAIN}" >&2
  exit 1
fi

python3 - "${MAIN}" "${DOTENV_DIR}" <<'PY'
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

main = Path(sys.argv[1]).resolve()
dotenv_dir = Path(sys.argv[2]).resolve()
dotenv_dir.mkdir(mode=0o700, exist_ok=True)

relatives = (".env", Path("docker") / ".env")
canonical = {
    ".env": dotenv_dir / "root.env",
    str(Path("docker") / ".env"): dotenv_dir / "docker.env",
}


def is_fifo(path: Path) -> bool:
    try:
        return stat.S_ISFIFO(path.lstat().st_mode)
    except FileNotFoundError:
        return False


def seed_if_needed(target: Path, example: Path) -> None:
    if target.is_symlink() or (target.exists() and target.is_file() and not is_fifo(target)):
        os.chmod(target, 0o600)
        return
    if is_fifo(target) or target.exists():
        target.unlink()
    if example.is_file():
        target.write_bytes(example.read_bytes())
    else:
        target.write_text("", encoding="utf-8")
    os.chmod(target, 0o600)


def rel_link(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink() or is_fifo(link) or (link.exists() and link.stat().st_size == 0):
        link.unlink()
    elif link.exists() and not link.is_symlink():
        print(f"skip existing file {link}")
        return
    link.symlink_to(os.path.relpath(target, start=link.parent))
    print(f"link {link} -> {target}")


seed_if_needed(canonical[".env"], main / ".env.example")
seed_if_needed(canonical[str(Path("docker") / ".env")], main / "docker" / ".env.example")

# Main worktree: root `.env` and `docker/.env` point at dotenv/.
for rel in relatives:
    rel_link(main / rel, canonical[str(rel)])

# Other worktrees: same relative names, still pointing at the main dotenv dir.
porcelain = os.popen(f"git -C {main.as_posix()} worktree list --porcelain").read().splitlines()
paths: list[Path] = []
for line in porcelain:
    if line.startswith("worktree "):
        paths.append(Path(line.split(" ", 1)[1]))

for wt in paths:
    wt = wt.resolve()
    if wt == main:
        continue
    if not wt.is_dir():
        print(f"skip missing {wt}")
        continue
    for rel in relatives:
        rel_link(wt / rel, canonical[str(rel)])
PY
