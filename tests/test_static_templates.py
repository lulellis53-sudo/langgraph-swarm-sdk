"""Static template smoke and concurrency alignment."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

from swarm_sdk.execution.concurrency import parallel_cap
from swarm_sdk.execution.executor import _pool_workers

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / ".cursor/templates/python_static_template.py"
TEMPLATE_LITE = ROOT / ".cursor/templates/python_static_template_lite.py"
AGENTS = ROOT / "AGENTS.md"


def test_parallel_cap_matches_executor_pool() -> None:
    assert parallel_cap() == _pool_workers()
    assert parallel_cap() in (8, 32)


def test_agents_md_does_not_embed_full_template() -> None:
    text = AGENTS.read_text()
    assert "class wrappers:" not in text
    assert "python_static_template.py" in text
    assert "python_static_template_lite.py" in text


def test_static_template_smoke() -> None:
    subprocess.run([sys.executable, str(TEMPLATE)], check=True, cwd=ROOT)


def test_static_template_lite_smoke() -> None:
    subprocess.run([sys.executable, str(TEMPLATE_LITE)], check=True, cwd=ROOT)


def test_retry_transient_does_not_retry_value_error() -> None:
    spec = importlib.util.spec_from_file_location("static_template_under_test", TEMPLATE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    calls = 0

    @module.wrappers.retry_transient(times=3)
    def boom() -> None:
        nonlocal calls
        calls += 1
        raise ValueError("logic bug")

    try:
        boom()
    except ValueError:
        pass
    assert calls == 1
