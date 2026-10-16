"""Import-laziness and free-threading safety checks for the WebSearch module."""

from __future__ import annotations

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from WebSearch.agents.agent_tools import count_tokens
from WebSearch.frontend import http_utils

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HEAVY = ("tiktoken", "httpx", "httpx2", "pandas", "fastapi", "langchain_core", "swarm_sdk")


@pytest.mark.parametrize(
    "module", ["WebSearch", "WebSearch.agents.agent_tools", "WebSearch.app.cli"]
)
def test_entry_points_do_not_import_heavy_dependencies(module: str) -> None:
    code = (
        f"import sys, {module}\n"
        f"loaded = [m for m in {_HEAVY!r} if m in sys.modules]\n"
        "print(','.join(loaded))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    assert result.stdout.strip() == ""


def test_shared_http_client_is_a_singleton_under_contention() -> None:
    with ThreadPoolExecutor(max_workers=32) as pool:
        clients = list(pool.map(lambda _: http_utils.shared_http_client(), range(64)))
    assert len({id(c) for c in clients}) == 1


def test_count_tokens_is_consistent_across_threads() -> None:
    text = "free-threaded Python 3.15t counts tokens identically in every thread"
    expected = count_tokens(text)
    with ThreadPoolExecutor(max_workers=32) as pool:
        counts = list(pool.map(lambda _: count_tokens(text), range(256)))
    assert set(counts) == {expected}
    assert expected > 0
