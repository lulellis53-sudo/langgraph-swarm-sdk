"""The full agent template: role classes and role functions behave as documented."""

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
ROLE_EXPORTS = (
    "wrappers",
    "TypeRole",
    "HintRole",
    "VectRole",
    "MathRole",
    "DbRole",
    "BatchRole",
    "LoopRole",
    "CoworkRole",
    "type_is_mapping",
    "hint_tag",
    "vect_l2",
    "math_safe_div",
    "db_uri",
    "batch_chunked",
    "loop_chunked",
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


def test_role_exports_are_exact(tpl: ModuleType) -> None:
    assert tuple(tpl.__all__) == ROLE_EXPORTS
    role_functions = tuple(
        name
        for name in tpl.__all__
        if name.startswith(PREFIXES) and callable(getattr(tpl, name))
    )
    assert sorted(role_functions) == sorted(
        name for name in ROLE_EXPORTS if name.startswith(PREFIXES)
    )


def test_type_role(tpl: ModuleType) -> None:
    assert tpl.TypeRole.ensure_str("x") == "x"
    with pytest.raises(TypeError):
        tpl.TypeRole.ensure_str(5)
    assert tpl.type_is_mapping({}) is True
    assert tpl.type_is_mapping([]) is False


def test_vector_functions(tpl: ModuleType) -> None:
    v = tpl.VectRole(dim=3)
    assert v.zeros() == [0.0, 0.0, 0.0]
    assert v.dot([1, 2, 3], [4, 5, 6]) == 32
    assert tpl.vect_l2([0, 0], [3, 4]) == 5.0
    with pytest.raises(ValueError, match="length mismatch"):
        v.dot([1], [1, 2])


def test_math_functions(tpl: ModuleType) -> None:
    assert tpl.MathRole.clamp(5, 0, 1) == 1 and tpl.MathRole.clamp(-1, 0, 1) == 0
    assert tpl.math_safe_div(6, 3) == 2 and tpl.math_safe_div(1, 0, default=-1) == -1


def test_db_uri_round_trips_through_sqlite(tpl: ModuleType, tmp_path: Path) -> None:
    path = str(tmp_path / "t.sqlite")
    with sqlite3.connect(tpl.db_uri(path), uri=True) as conn:
        conn.execute("create table t (x int)")
    with sqlite3.connect(tpl.db_uri(path, read_only=True), uri=True) as conn:
        conn.execute("select * from t").fetchall()


def test_batch_chunked(tpl: ModuleType) -> None:
    assert tpl.batch_chunked([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]
    assert tpl.batch_chunked([], 3) == []
    assert tpl.loop_chunked([1, 2], 1) == [[1], [2]]
    with pytest.raises(ValueError, match="size must be >= 1"):
        tpl.batch_chunked([1], 0)


def test_cowork_cap_matches_sdk(tpl: ModuleType) -> None:
    from swarm_sdk.execution import gil_enabled, parallel_cap

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

    async def main() -> tuple[list[int], int]:
        coros = [job(i, 0.01) for i in range(12)]
        ordered = await tpl.BatchRole.gather_limited(coros, limit=4)
        return ordered, peak

    ordered, observed_peak = asyncio.run(main())
    assert ordered == list(range(12))
    assert observed_peak <= 4


@pytest.mark.parametrize("name", ["python_static_template.py", "python_static_template_lite.py"])
def test_templates_run_their_smoke_check(name: str) -> None:
    result = subprocess.run(
        [sys.executable, str(TEMPLATES / name)], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr[-400:]
