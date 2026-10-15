#!/usr/bin/env bash
# Sync feat/botdeal worktree at ../BotDeal with feat/prediction-engine.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREDICTION_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SWARM_ROOT="$(cd "${PREDICTION_DIR}/.." && pwd)"
BOTDEAL_PATH="${BOTDEAL_WORKTREE:-${SWARM_ROOT}/../BotDeal}"
SOURCE_BRANCH="${BOTDEAL_SOURCE_BRANCH:-feat/prediction-engine}"
TARGET_BRANCH="${BOTDEAL_BRANCH:-feat/botdeal}"

cd "${SWARM_ROOT}"

if ! git rev-parse --verify "${SOURCE_BRANCH}" >/dev/null 2>&1; then
  echo "error: missing source branch ${SOURCE_BRANCH}" >&2
  exit 1
fi

if ! git rev-parse --verify "${TARGET_BRANCH}" >/dev/null 2>&1; then
  echo "creating branch ${TARGET_BRANCH} from ${SOURCE_BRANCH}"
  git branch "${TARGET_BRANCH}" "${SOURCE_BRANCH}"
fi

if [[ -d "${BOTDEAL_PATH}/.git" ]] || [[ -f "${BOTDEAL_PATH}/.git" ]]; then
  echo "worktree already present: ${BOTDEAL_PATH}"
else
  echo "adding worktree ${BOTDEAL_PATH} on ${TARGET_BRANCH}"
  git worktree add "${BOTDEAL_PATH}" "${TARGET_BRANCH}"
fi

echo "merging ${SOURCE_BRANCH} -> ${TARGET_BRANCH} in ${BOTDEAL_PATH}"
git -C "${BOTDEAL_PATH}" merge "${SOURCE_BRANCH}" -m "sync: ${SOURCE_BRANCH} -> ${TARGET_BRANCH}"

echo "done: $(git -C "${BOTDEAL_PATH}" rev-parse --short HEAD) on ${TARGET_BRANCH}"
