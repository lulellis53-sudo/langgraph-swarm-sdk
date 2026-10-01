"""Heavy optional packages must not load on ``import swarm_sdk``."""

from __future__ import annotations

import subprocess
import sys


def _loaded_after_import(*names: str) -> set[str]:
    code = (
        "import sys, swarm_sdk; "
        f"print(','.join(n for n in {names!r} if n in sys.modules))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=180,
        check=True,
    ).stdout.strip()
    return {n for n in out.split(",") if n}


def test_import_swarm_sdk_does_not_load_polars() -> None:
    assert "polars" not in _loaded_after_import("polars")


def test_import_swarm_sdk_does_not_load_embedding_backends() -> None:
    assert not _loaded_after_import("fastembed", "llama_cpp")
