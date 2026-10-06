"""``async_wrapper`` must offload to the shared executor (it imported a missing module)."""

from __future__ import annotations

import threading

import pytest

from swarm_sdk.compute.report import _gil_status
from swarm_sdk.decorators import async_wrapper


async def test_async_wrapper_runs_sync_function_off_the_event_loop_thread() -> None:
    caller = threading.get_ident()

    @async_wrapper
    def blocking(a: int, b: int = 1) -> tuple[int, int]:
        return a + b, threading.get_ident()

    total, worker = await blocking(2, b=3)
    assert total == 5
    assert worker != caller


@pytest.mark.parametrize(("gil", "label"), [(True, "enabled"), (False, "disabled")])
def test_gil_status_follows_the_shared_probe(
    monkeypatch: pytest.MonkeyPatch, gil: bool, label: str
) -> None:
    monkeypatch.setattr("swarm_sdk.runtime.concurrency.gil_enabled", lambda: gil)
    assert _gil_status() == label
