"""U-shaped passage ordering and its wiring into SwarmSDK._recall."""

from __future__ import annotations

from pathlib import Path

from benchmark.tests.fakes import sdk_with_router

from swarm_sdk.config.loader import RagConfig
from swarm_sdk.retrieval.ordering import order_for_prompt, u_shape


def test_u_shape_puts_best_first_and_second_best_last() -> None:
    assert u_shape(["r1", "r2", "r3", "r4", "r5"]) == ["r1", "r3", "r5", "r4", "r2"]
    assert u_shape(["r1", "r2", "r3", "r4"]) == ["r1", "r3", "r4", "r2"]


def test_u_shape_small_and_non_ascii_inputs() -> None:
    assert u_shape([]) == []
    assert u_shape(["a"]) == ["a"]
    assert u_shape(["a", "b"]) == ["a", "b"]
    assert sorted(u_shape(["café", "東京", "ß"])) == sorted(["café", "東京", "ß"])


def test_order_for_prompt_is_identity_when_disabled() -> None:
    items = ["a", "b", "c", "d"]
    assert order_for_prompt(items, enabled=False) == items
    assert order_for_prompt(items, enabled=True) == u_shape(items)


def test_rag_config_defaults_are_off() -> None:
    cfg = RagConfig()
    assert cfg.u_shape_order is False
    assert cfg.parent_child is False
    assert cfg.child_size == 400


def test_sdk_recall_honors_the_flag(tmp_path: Path) -> None:
    sdk = sdk_with_router(tmp_path, "{}")
    for text in ["alpha cache", "beta cache", "gamma cache", "delta cache"]:
        sdk.memory.add(text, sdk.embedder.embed([text], query=False)[0])
    off = sdk._recall("cache")
    assert len(off) >= 3
    sdk.file_config.rag.u_shape_order = True
    on = sdk._recall("cache")
    assert on == u_shape(off)
