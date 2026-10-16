"""Offline tests for the Webengine agentic tool belt (factories, namespaces, async)."""

from __future__ import annotations

import asyncio

from WebSearch.frontend.websearchers import ProvidersConfig, SearcherSpec, SearchHit
from WebSearch.Webengine import (
    TOOL_NAMES,
    Data,
    DeepResearch,
    DocFormat,
    FileType,
    Functions,
    Parameters,
    Playwright,
    SemanticSearch,
    Summarize,
    WebFetch,
    Websearch,
    Websearch_DisableProvider,
    aWebsearch,
    dispatch,
    manifest,
)


def _config() -> ProvidersConfig:
    """Minimal registry with two fake searchers."""
    return ProvidersConfig(
        version=1,
        searchers=(
            SearcherSpec(id="fake", kind="websearcher", enabled=True),
            SearcherSpec(id="other", kind="websearcher", enabled=True),
        ),
    )


def _backends() -> dict[str, object]:
    """Two fake backends returning distinct hits."""

    def fake(query: str, spec: SearcherSpec) -> list[SearchHit]:
        return [
            SearchHit(
                title="Webengine result",
                url="https://example.com/engine",
                snippet="Token-lean structured result.",
                searcher_id=spec.id,
            )
        ]

    def other(query: str, spec: SearcherSpec) -> list[SearchHit]:
        return [
            SearchHit(
                title="Other provider hit",
                url="https://other.example/item",
                snippet="Should vanish when disabled.",
                searcher_id=spec.id,
            )
        ]

    return {"fake": fake, "other": other}


_HTML = b"<html><body><article><p>Fetched page content here for tests.</p></article></body></html>"


def test_functions_returns_named_langchain_tools() -> None:
    """Functions() exposes the standard belt with stable names."""
    tools = Functions(config=_config(), backends=_backends(), fetch=lambda url: _HTML)
    names = [tool.name for tool in tools]
    assert "web_search" in names
    assert "web_search_brief" in names
    assert "web_open_page" in names
    assert "web_dedupe" in names
    assert names[0] == "web_search"


def test_functions_brief_tool_is_token_budgeted() -> None:
    """The brief tool in the belt accepts max_tokens."""
    tools = Functions(config=_config(), backends=_backends())
    brief = next(tool for tool in tools if tool.name == "web_search_brief")
    assert "max_tokens" in brief.args
    result = brief.invoke({"query": "webengine", "max_tokens": 120})
    assert "Webengine result" in result


def test_manifest_and_dispatch_round_trip() -> None:
    """manifest() lists the core tools; dispatch() executes web_search hits."""
    names = {entry["function"]["name"] for entry in manifest(format="openai")}
    assert set(TOOL_NAMES) <= names
    result = dispatch(
        "web_search",
        {"query": "webengine", "limit": 2},
        config=_config(),
        backends=_backends(),
    )
    assert result["hits"][0]["url"] == "https://example.com/engine"


def test_dispatch_unknown_tool_is_structured_error() -> None:
    """Unknown tools return an error dict, never raise."""
    result = dispatch("nope", {})
    assert "error" in result


def test_websearch_factory_returns_single_tool() -> None:
    """Websearch() builds one token-budgeted ``websearch`` BaseTool."""
    tool = Websearch(backends=_backends())
    assert tool.name == "websearch"
    assert "max_tokens" in tool.args
    result = tool.invoke({"query": "webengine", "max_tokens": 120})
    assert "Webengine result" in result
    assert "Sources:" in result


def test_websearch_decorator_attaches_tool() -> None:
    """@Websearch(...) returns the function and attaches ``.websearch_tool``."""

    @Websearch(backends=_backends(), limit=3, max_tokens=200)
    def assistant(query: str) -> str:
        return f"agent:{query}"

    assert assistant("hi") == "agent:hi"
    tool = assistant.websearch_tool
    assert tool.name == "websearch"
    brief = tool.invoke({"query": "webengine"})
    assert "Webengine result" in brief


def test_websearch_disable_provider_drops_hits() -> None:
    """Websearch_DisableProvider excludes the named provider for this tool only."""
    tool = Websearch_DisableProvider(disable=["OTHER"], backends=_backends())
    brief = tool.invoke({"query": "webengine"})
    assert "Webengine result" in brief
    assert "Other provider hit" not in brief


def test_await_asearch_skips_disabled_provider() -> None:
    """AWebsearch runs off-loop and honors disable for that call only."""
    brief = asyncio.run(aWebsearch("webengine", backends=_backends(), disable=["other"]))
    assert "Webengine result" in brief
    assert "Other provider hit" not in brief


def test_namespaces_expose_data_parameters_filetype() -> None:
    """Websearch.Data/.Parameters/.FileType namespaces resolve as documented."""
    assert Websearch.Data is Data
    assert Websearch.Parameters is Parameters
    assert Websearch.FileType is FileType
    before = Data.Before(query="q")
    assert before.firsts.limit == 5
    seconds = Parameters.Seconds()
    assert seconds.fetch_limit == 3
    assert FileType.MARKDOWN.value == "markdown"


def test_webfetch_tool_extracts_injected_html() -> None:
    """WebFetch returns extracted text from an injected fetch callable."""
    tool = WebFetch(fetch=lambda url: _HTML)
    assert tool.name == "web_fetch"
    text = tool.invoke({"url": "https://example.com/page"})
    assert "Fetched page content" in text


def test_playwright_tool_requires_browser() -> None:
    """Playwright tool exists; browsing without the browser fails closed."""
    tool = Playwright()
    assert tool.name == "web_browse"
    import importlib.util

    if importlib.util.find_spec("playwright") is None:
        import pytest

        with pytest.raises(OSError):
            tool.invoke({"url": "https://example.com/js"})


def test_summarize_and_semantic_tools_construct() -> None:
    """Summarize/SemanticSearch build with the expected names and schemas."""
    summarize = Summarize()
    assert summarize.name == "web_summarize"
    assert "documents" in summarize.args
    semantic = SemanticSearch()
    assert semantic.name == "web_semantic_search"
    assert "query" in semantic.args


def test_deep_research_runs_offline_pipeline() -> None:
    """DeepResearch searches fakes, fetches pages, and returns brief+pages."""
    tool = DeepResearch(backends=_backends(), fetch=lambda url: _HTML)
    result = tool.invoke({"query": "webengine", "limit": 2, "fetch_limit": 2})
    assert "Webengine result" in result["brief"]
    assert any(page["url"].endswith("/engine") for page in result["pages"])


def test_docformat_markdown_and_json() -> None:
    """DocFormat normalizes, dedupes, and re-emits documents in the file type."""
    docs = [
        {"url": "https://a.example/1", "text": "  Alpha   content  "},
        {"url": "https://a.example/1", "text": "Alpha content"},  # duplicate after normalize
    ]
    markdown = DocFormat(file_type=FileType.MARKDOWN).invoke({"documents": docs})
    assert markdown["file_type"] == "markdown"
    assert markdown["count"] == 1
    assert markdown["removed"] == 1
    assert markdown["documents"][0].startswith("## https://a.example/1")

    as_json = DocFormat(file_type=FileType.JSON).invoke({"documents": docs})
    assert as_json["file_type"] == "json"
    assert isinstance(as_json["documents"][0], dict)
