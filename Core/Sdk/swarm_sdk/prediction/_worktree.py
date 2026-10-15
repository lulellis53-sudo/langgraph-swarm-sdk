"""Shared worktree import bootstrap for the prediction package."""

from __future__ import annotations

import sys
from pathlib import Path

__all__ = ["ensure_repo_on_path"]


def ensure_repo_on_path() -> None:
    """Put the repository root on ``sys.path`` so worktree packages import.

    The ``WebSearch`` searchers and the ``Prediction`` forecast engine live in
    sibling top-level packages of the main checkout; importing them from an
    installed SDK needs the repo root importable once.
    """
    repo_root = str(Path(__file__).resolve().parents[3])
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
