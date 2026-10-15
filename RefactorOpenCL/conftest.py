"""Repo-root conftest: keep the repository root importable in every pytest invocation.

Data directories under ``Agents/`` (e.g. ``Agents/Prediction``) share names with
real root packages (``Prediction``, ``WebSearch``). When pytest prepends an
``Agents/`` basedir to ``sys.path`` and the root is absent, those data dirs
resolve as shadow namespace packages. Importing this conftest pins the root
first so the regular packages always win the import scan.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
