"""Tests for agent tools, fallback factories, and calculations."""

from __future__ import annotations

import sys
import types

import pytest

from langswarm.tools import get_tool


def test_tool_registry_contains_expected_tools() -> None:
    """Ensure all core tools referenced by the 12 agents are registered."""
    expected_tools = {
        "rag_search",
        "fetch_notes",
        "rag_ingest",
        "draft_outline",
        "calculate",
        "critique_draft",
        "inspect_dataset",
        "validate_dataset",
        "fetch_url",
        "save_memory",
        "search_memory",
        "run_benchmarks",
        "finalize_response",
    }
    for tool_name in expected_tools:
        tool = get_tool(tool_name)
        assert tool is not None, f"Tool {tool_name} was not found in registry"
        assert callable(tool) or hasattr(tool, "invoke") or hasattr(tool, "func")


def test_calculate_tool() -> None:
    """Test SymPy arithmetic and symbolic evaluation tool."""
    calc_tool = get_tool("calculate")
    assert calc_tool is not None

    # Test arithmetic
    result = calc_tool.invoke({"expression": "2**10"})
    assert "1024" in str(result)

    # Test algebra
    result_sym = calc_tool.invoke({"expression": "x + 2*x"})
    assert "3*x" in str(result_sym)


def test_inspect_dataset_tool() -> None:
    """Test polars dataset inspection tool."""
    inspect_tool = get_tool("inspect_dataset")
    assert inspect_tool is not None

    # Test on the sample.csv included in langswarm
    result = inspect_tool.invoke({"path": "data/sample.csv"})
    res_str = str(result).lower()
    assert "columns" in res_str or "shape" in res_str or "id" in res_str


def test_websearch_tool_resolves_from_webengine(monkeypatch: pytest.MonkeyPatch) -> None:
    """The websearch entry builds Websearch() from WebSearch.Webengine, with no network."""
    sentinel = object()
    calls: list[dict[str, object]] = []

    def fake_websearch(**kwargs: object) -> object:
        calls.append(kwargs)
        return sentinel

    pkg = types.ModuleType("WebSearch")
    engine = types.ModuleType("WebSearch.Webengine")
    monkeypatch.setattr(engine, "Websearch", fake_websearch, raising=False)
    monkeypatch.setattr(pkg, "Webengine", engine, raising=False)
    monkeypatch.setitem(sys.modules, "WebSearch", pkg)
    monkeypatch.setitem(sys.modules, "WebSearch.Webengine", engine)

    assert get_tool("websearch") is sentinel
    assert calls == [{}]


def test_websearch_tool_missing_package_raises_import_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without the WebSearch package installed, resolving the tool fails with ImportError."""
    monkeypatch.setitem(sys.modules, "WebSearch", None)
    monkeypatch.setitem(sys.modules, "WebSearch.Webengine", None)

    with pytest.raises(ImportError):
        get_tool("websearch")

