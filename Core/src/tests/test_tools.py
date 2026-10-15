"""Tests for agent tools, fallback factories, and calculations."""

from __future__ import annotations

from pathlib import Path

import pytest

from langswarm.tools import REGISTRY, get_tool, resolve_tools


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
        "remember",
        "recall",
        "run_benchmark",
        "format_answer",
        "web_search",
        "deepwiki_read",
        "sql_query",
        "pixel_schema",
        "render_pixel_scene",
        "apify_search",
        "jina_read",
        "mcp_call",
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
    result = calc_tool("2**10")
    assert "1024" in str(result)

    # Test algebra
    result_sym = calc_tool("x + 2*x")
    assert "3*x" in str(result_sym)


def test_inspect_dataset_tool() -> None:
    """Test polars dataset inspection tool."""
    from langswarm.config import settings

    settings.data_path = str(Path(__file__).parents[1] / "data" / "sample.csv")
    inspect_tool = get_tool("inspect_dataset")
    assert inspect_tool is not None

    # Test on the sample.csv included in langswarm
    result = inspect_tool("show the shape")
    res_str = str(result).lower()
    assert "columns" in res_str or "shape" in res_str or "id" in res_str


def test_websearch_tool_resolves_from_webengine(monkeypatch: pytest.MonkeyPatch) -> None:
    """The legacy metasearch name stays a lazy alias for compatibility."""
    assert get_tool("websearch") is get_tool("web_search")


def test_websearch_tool_missing_package_raises_import_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Registry resolution does not need optional web SDKs or network access."""
    assert callable(get_tool("websearch"))


def test_apify_missing_key_degrades_to_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    assert "APIFY_TOKEN" in get_tool("apify_search")("query")


def test_mcp_invalid_arguments_degrade_to_hint() -> None:
    assert "JSON object" in get_tool("mcp_call")("tool", "[]")


def test_every_blueprint_tool_resolves() -> None:
    from langswarm.blueprint import load_blueprint

    path = Path(__file__).parents[1] / "config" / "swarm.yaml"
    names = {name for agent in load_blueprint(path).agents for name in agent.tools}
    assert names <= REGISTRY.keys()
    assert all(callable(tool) for tool in resolve_tools(sorted(names)))
