"""Smoke imports for the unified Core Lang dependency stack."""

from __future__ import annotations


def test_langgraph_and_langchain_core_importable() -> None:
    import langchain_core  # noqa: F401
    import langgraph  # noqa: F401


def test_orchestration_graph_module_importable() -> None:
    import orchestration.graph  # noqa: F401


def test_core_lang_facade_exports() -> None:
    from Core.Lang import GraphBuilder, build_graph, tracing_enabled

    assert callable(build_graph)
    assert callable(tracing_enabled)
    assert GraphBuilder is not None
