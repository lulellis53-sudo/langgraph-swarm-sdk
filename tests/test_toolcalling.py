"""Offline tests for the framework-agnostic tool-calling layer.

Fake backends and a fake fetch only — no network, no API keys.
"""

from __future__ import annotations

import json

import pytest
from WebSearch.frontend.websearchers import ProvidersConfig, SearcherSpec, SearchHit
from WebSearch.toolcalling import ToolError, bind_tools, dispatch_tool_call, tool_manifests


def _config() -> ProvidersConfig:
    return ProvidersConfig(
        version=1,
        searchers=(SearcherSpec(id="fake", kind="websearcher", enabled=True),),
        extractor_order=("selectolax",),
    )


def _backends():
    def backend(query: str, spec: SearcherSpec) -> list[SearchHit]:
        del spec
        return [
            SearchHit(
                title=f"Result for {query}",
                url="https://example.com/article",
                snippet="On 2026-10-01 it cost R$ 100",
                searcher_id="fake",
            )
        ]

    return {"fake": backend}


PAGE = b"<html><body><h1>Deep page</h1><p>The real analysis lives here.</p></body></html>"


def test_manifests_openai_and_anthropic_shapes() -> None:
    openai_tools = tool_manifests(format="openai")
    assert all(tool["type"] == "function" for tool in openai_tools)
    assert {tool["function"]["name"] for tool in openai_tools} == {
        "web_search",
        "web_open_page",
        "web_dedupe",
    }
    anthropic_tools = tool_manifests(format="anthropic")
    assert all("input_schema" in tool and "name" in tool for tool in anthropic_tools)
    with pytest.raises(ToolError, match="unknown manifest format"):
        tool_manifests(format="mcp")


def test_dispatch_web_search_returns_structured_hits() -> None:
    result = dispatch_tool_call(
        "web_search", {"query": "rtx 5090", "limit": 3}, backends=_backends()
    )
    assert len(result["hits"]) == 1
    assert result["hits"][0]["searcher"] == "fake"
    assert result["hits"][0]["url"] == "https://example.com/article"


def test_dispatch_accepts_json_string_arguments() -> None:
    result = dispatch_tool_call("web_search", json.dumps({"query": "ddr5"}), backends=_backends())
    assert "Result for ddr5" in result["hits"][0]["title"]


def test_dispatch_errors_are_agent_readable_not_exceptions() -> None:
    unknown = dispatch_tool_call("nope", {})
    assert "unknown tool" in unknown["error"] and "web_search" in unknown["known_tools"]
    missing = dispatch_tool_call("web_search", {})
    assert "missing required argument" in missing["error"]
    bad_type = dispatch_tool_call("web_search", {"query": "x", "limit": "many"})
    assert "must be an integer" in bad_type["error"]
    out_of_range = dispatch_tool_call("web_search", {"query": "x", "limit": 99})
    assert "must be <=" in out_of_range["error"]
    bad_json = dispatch_tool_call("web_search", "{not json")
    assert "not valid JSON" in bad_json["error"]
    bad_url = dispatch_tool_call("web_open_page", {"url": "javascript:alert(1)"})
    assert "pattern" in bad_url["error"] or "does not match" in bad_url["error"]


def test_dispatch_open_page_uses_injected_fetch_and_blocks_loopback() -> None:
    result = dispatch_tool_call(
        "web_open_page", {"url": "https://example.com/deep"}, fetch=lambda url: PAGE
    )
    assert "real analysis" in result["text"]
    assert result["extractor"]
    loopback = dispatch_tool_call("web_open_page", {"url": "http://127.0.0.1:8080/admin"})
    assert "loopback" in loopback["error"]


def test_dispatch_dedupe_drops_near_duplicates() -> None:
    docs = [
        {
            "url": "https://a.example/1",
            "text": "LightGBM builds gradient boosted trees for forecasting time series data.",
        },
        {
            "url": "https://b.example/2",
            "text": "LightGBM builds gradient boosted trees for forecasting time series data.",
        },
        {
            "url": "https://c.example/3",
            "text": "Completely different content about ceramic kilns and glazes.",
        },
    ]
    result = dispatch_tool_call("web_dedupe", {"documents": docs})
    assert {doc["url"] for doc in result["unique"]} >= {"https://a.example/1"}
    assert "https://b.example/2" in result["dropped"]


def test_bind_tools_roundtrip() -> None:
    tools, run_tool = bind_tools(backends=_backends())
    assert tools[0]["function"]["name"] == "web_search"
    result = run_tool("web_search", {"query": "probe"})
    assert result["hits"]


def test_loopback_blocked_inside_dispatch() -> None:
    blocked = dispatch_tool_call("web_open_page", {"url": "http://localhost/x"})
    assert "loopback" in blocked["error"]
