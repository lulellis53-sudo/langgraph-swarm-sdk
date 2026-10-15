"""Importing ``swarm_sdk.serving`` must not build the default app (it primes real secrets)."""

from __future__ import annotations

import subprocess
import sys

CODE = """
import sys
import swarm_sdk.serving as serving
http = sys.modules["swarm_sdk.serving.http"]
assert http._app is None, "default app was built at import time"
assert callable(vars(serving).get("__getattr__")), "serving must resolve `app` lazily"
"""


def test_importing_serving_does_not_build_the_default_app() -> None:
    result = subprocess.run(
        [sys.executable, "-c", CODE], capture_output=True, text=True, timeout=120, check=False
    )
    assert result.returncode == 0, result.stderr[-400:]
