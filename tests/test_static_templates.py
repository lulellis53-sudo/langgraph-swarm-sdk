"""The full agent template: exactly eleven role functions, each behaving as documented."""

from __future__ import annotations

import asyncio
import importlib.util
import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

TEMPLATES = Path(__file__).resolve().parents[1] / ".cursor" / "templates"
ROLE_FUNCTIONS = (
    "type_is_mapping",
    "type_ensure_str",
    "hint_tag",
    "vect_dot",
    "vect_l2",
    "math_clamp",
    "math_safe_div",
    "db_uri",
    "batch_chunked",
    "cowork_gil_enabled",
    "cowork_parallel_cap",
)
PREFIXES = ("type_", "hint_", "vect_", "math_", "db_", "batch_", "cowork_")


@pytest.fixture(scope="module")
def tpl() -> Iterator[ModuleType]:
    spec = importlib.util.spec_from_file_location(
        "python_static_template", TEMPLATES / "python_static_template.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve annotations through sys.modules
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(spec.name, None)


def test_exactly_eleven_role_functions(tpl: ModuleType) -> None:
    exported = tuple(
        name for name in tpl.__all__ if name.startswith(PREFIXES) and callable(getattr(tpl, name))
    )
    assert sorted(exported) == sorted(ROLE_FUNCTIONS)
    assert len(exported) == 11


@pytest.mark.parametrize("name", ["python_static_template.py", "python_static_template_lite.py"])
def test_templates_run_their_smoke_check(name: str) -> None:
    result = subprocess.run(
        [sys.executable, str(TEMPLATES / name)], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr


def test_type_functions(tpl: ModuleType) -> None:
    assert tpl.type_is_mapping({"a": 1}) and not tpl.type_is_mapping(["a"])
    assert tpl.type_ensure_str("x") == "x"
    with pytest.raises(TypeError, match="expected str, got int"):
        tpl.type_ensure_str(1)


def test_vector_functions(tpl: ModuleType) -> None:
    assert tpl.vect_dot([1, 2, 3], [4, 5, 6]) == 32.0
    assert tpl.vect_l2([0, 0], [3, 4]) == 5.0
    for fn in (tpl.vect_dot, tpl.vect_l2):
        with pytest.raises(ValueError, match="length mismatch"):
            fn([1], [1, 2])


def test_math_functions(tpl: ModuleType) -> None:
    assert tpl.math_clamp(5, 0, 1) == 1 and tpl.math_clamp(-1, 0, 1) == 0
    with pytest.raises(ValueError, match="lo must be <= hi"):
        tpl.math_clamp(0, 2, 1)
    assert tpl.math_safe_div(6, 3) == 2 and tpl.math_safe_div(1, 0, default=-1) == -1


def test_db_uri_round_trips_through_sqlite(tpl: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "a dir#1" / "x.db"
    path.parent.mkdir()
    with sqlite3.connect(tpl.db_uri(path), uri=True) as conn:
        conn.execute("CREATE TABLE t (v INTEGER)")
    with sqlite3.connect(tpl.db_uri(path, read_only=True), uri=True) as conn:
        assert conn.execute("SELECT count(*) FROM t").fetchone() == (0,)
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO t VALUES (1)")


def test_batch_chunked(tpl: ModuleType) -> None:
    assert tpl.batch_chunked([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]
    assert tpl.batch_chunked([], 3) == []
    with pytest.raises(ValueError, match="size must be >= 1"):
        tpl.batch_chunked([1], 0)


def test_cowork_cap_matches_sdk(tpl: ModuleType) -> None:
    from swarm_sdk.execution.concurrency import gil_enabled, parallel_cap

    assert tpl.cowork_gil_enabled() == gil_enabled()
    assert tpl.cowork_parallel_cap() == parallel_cap()


def test_gather_limited_keeps_input_order_and_cap(tpl: ModuleType) -> None:
    running = peak = 0

    async def job(value: int, delay: float) -> int:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(delay)
        running -= 1
        return value

    coros = [job(i, 0.02 - i * 0.004) for i in range(5)]
    results = asyncio.run(tpl.BatchRole.gather_limited(coros, limit=2))
    assert results == [0, 1, 2, 3, 4]
    assert peak == 2


def test_retry_transient_counts_attempts_and_skips_logic_errors(tpl: ModuleType) -> None:
    calls = 0

    @tpl.wrappers.retry_transient(times=3)
    def flaky() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise TimeoutError("slow")
        return "ok"

    assert flaky() == "ok" and calls == 3

    bad = 0

    @tpl.wrappers.retry_transient(times=3)
    def broken() -> None:
        nonlocal bad
        bad += 1
        raise ValueError("logic")

    with pytest.raises(ValueError, match="logic"):
        broken()
    assert bad == 1
