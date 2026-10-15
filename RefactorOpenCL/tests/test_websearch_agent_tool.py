"""Offline tests for the new agent-facing ``search``, ``asearch`` and ``as_tool``.

These exercise the keyless-by-default pipeline with fake backends so no API
keys or network are required.
"""

from __future__ import annotations

import asyncio

from WebSearch.agent_tools import as_tool, asearch, search
from WebSearch.frontend.websearchers import (
    ProvidersConfig,
    SearcherSpec,
    SearchHit,
)


def _config(*searcher_ids: str, enabled: bool = True) -> ProvidersConfig:
    """Build a minimal config containing only the given searcher ids."""
    return ProvidersConfig(
        version=1,
        searchers=tuple(
            SearcherSpec(id=sid, kind="websearcher", enabled=enabled) for sid in searcher_ids
        ),
        extractor_order=("selectolax", "selectolax_regex", "regex", "trafilatura", "bs4"),
    )


def _hit(title: str, url: str, snippet: str, searcher: str) -> SearchHit:
    """Build a search hit."""
    return SearchHit(title=title, url=url, snippet=snippet, searcher_id=searcher)


def test_search_reports_disabled_status() -> None:
    """A disabled searcher is reported as ``disabled`` and contributes no hits."""
    config = _config("needs_key", enabled=False)

    def backend(query: str, spec: SearcherSpec) -> list[SearchHit]:
        return [_hit("should not appear", "https://x.example/", "body", spec.id)]

    result = search("query", config=config, backends={"needs_key": backend})
    assert result.hits == ()
    assert result.status["needs_key"].status == "disabled"


def test_search_reports_no_key_status() -> None:
    """An enabled searcher that requires a missing key reports ``no_key``."""
    config = ProvidersConfig(
        version=1,
        searchers=(
            SearcherSpec(id="paid", kind="websearcher", api_key_env="PAID_API_KEY", enabled=True),
        ),
        extractor_order=("selectolax",),
    )
    result = search("query", config=config, backends={"paid": lambda q, s: []})
    assert result.hits == ()
    assert result.status["paid"].status == "no_key"


def test_search_reports_ok_status_and_returns_hits() -> None:
    """A ready searcher with a backend returns hits and reports ``ok``."""
    config = _config("free")

    def backend(query: str, spec: SearcherSpec) -> list[SearchHit]:
        return [_hit("answer", "https://answer.example/", "the answer", spec.id)]

    result = search("query", config=config, backends={"free": backend})
    assert len(result.hits) == 1
    assert result.hits[0].title == "answer"
    assert result.status["free"].status == "ok"


def test_search_enabled_ids_runtime_override() -> None:
    """``enabled_ids`` can activate a searcher that is disabled in config."""
    config = _config("alpha", "beta", enabled=False)

    def backend(query: str, spec: SearcherSpec) -> list[SearchHit]:
        return [_hit(spec.id, f"https://{spec.id}.example/", "body", spec.id)]

    result = search(
        "query",
        config=config,
        backends={"alpha": backend, "beta": backend},
        enabled_ids=["beta"],
    )
    assert [hit.searcher_id for hit in result.hits] == ["beta"]
    assert result.status["alpha"].status == "disabled"
    assert result.status["beta"].status == "ok"


def test_search_query_cache_returns_same_result() -> None:
    """The query-level cache returns the same object on identical inputs."""
    config = _config("cached")
    calls: list[str] = []

    def backend(query: str, spec: SearcherSpec) -> list[SearchHit]:
        calls.append(query)
        return [_hit("cached", "https://cached.example/", "body", spec.id)]

    first = search("query", config=config, backends={"cached": backend})
    second = search("query", config=config, backends={"cached": backend})
    assert first is second
    assert len(calls) == 1


def test_asearch_runs_search_in_thread() -> None:
    """``asearch`` returns the same result shape as ``search``."""
    config = _config("async")

    def backend(query: str, spec: SearcherSpec) -> list[SearchHit]:
        return [_hit("async result", "https://async.example/", "body", spec.id)]

    result = asyncio.run(asearch("query", config=config, backends={"async": backend}))
    assert len(result.hits) == 1
    assert result.status["async"].status == "ok"


def test_as_tool_returns_string_brief() -> None:
    """``as_tool`` builds a callable that returns a prompt-ready brief."""
    config = _config("tool")

    def backend(query: str, spec: SearcherSpec) -> list[SearchHit]:
        return [_hit("tool result", "https://tool.example/", "body", spec.id)]

    tool = as_tool(config=config, backends={"tool": backend}, max_tokens=200)
    brief = tool("query")
    assert isinstance(brief, str)
    assert "tool result" in brief
    assert "Sources:" in brief


def test_as_tool_respects_enabled_ids() -> None:
    """``as_tool`` forwards ``enabled_ids`` so only chosen providers run."""
    config = _config("a", "b", enabled=False)

    def backend(query: str, spec: SearcherSpec) -> list[SearchHit]:
        return [_hit(spec.id, f"https://{spec.id}.example/", "body", spec.id)]

    tool = as_tool(
        config=config,
        backends={"a": backend, "b": backend},
        enabled_ids=["a"],
        max_tokens=200,
    )
    brief = tool("query")
    assert "a" in brief
    assert "Sources: a" in brief
    assert "Sources: a, b" not in brief
