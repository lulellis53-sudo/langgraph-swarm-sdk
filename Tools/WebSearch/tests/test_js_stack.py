"""Offline tests for the JS-grade stack: DDG + Tavily + Exa fusion, Playwright/Crawlee failover.

No network and no browser: search backends are injected and crawler fetchers are
monkeypatched at the ``WebSearch.midend.crawl`` dispatch boundary, mirroring the
yaml crawler order (httpx → ... → scrapy → playwright → crawlee).
"""

from __future__ import annotations

import pytest
from WebSearch.frontend import providers as providers_mod
from WebSearch.frontend.fanout import search
from WebSearch.frontend.registry import load_providers
from WebSearch.frontend.types import CrawlSpec, ProvidersConfig, SearcherSpec, SearchHit
from WebSearch.midend import crawl as crawl_mod
from WebSearch.midend.crawl import ordered_fetch
from WebSearch.midend.crawlers import crawlee_start

_URL = "https://docs.example/guide"


def _hit(title: str, url: str, searcher: str) -> SearchHit:
    """Build a search hit."""
    return SearchHit(title=title, url=url, snippet="snippet body text", searcher_id=searcher)


def _searcher(sid: str) -> SearcherSpec:
    """Build an enabled websearcher spec."""
    return SearcherSpec(id=sid, kind="websearcher", enabled=True)


def test_ddg_tavily_exa_fuse_into_consensus_ranking() -> None:
    """The three-provider stack fuses, dedupes, and records cross-provider consensus."""
    config = ProvidersConfig(
        version=1,
        searchers=(_searcher("ddg"), _searcher("tavily"), _searcher("exa")),
    )
    backends = {
        "ddg": lambda q, s: [
            _hit("Guide", _URL, "ddg"),
            _hit("DDG only", "https://ddg-only.example/", "ddg"),
        ],
        "tavily": lambda q, s: [_hit("Guide (tavily)", _URL, "tavily")],
        "exa": lambda q, s: [_hit("Guide (exa)", _URL, "exa")],
    }

    result = search("guide", config=config, backends=backends, cache_ttl_s=0)

    assert result.status["ddg"].status == "ok"
    assert result.status["tavily"].status == "ok"
    assert result.status["exa"].status == "ok"
    consensus = next(h for h in result.hits if _URL in h.url)
    assert {"tavily", "exa"} <= {consensus.searcher_id, *consensus.also_from}


def test_packaged_yaml_enables_the_stack_and_js_crawlers() -> None:
    """ddg/tavily/exa are enabled searchers; playwright and crawlee are in crawler order."""
    cfg = load_providers()
    enabled = {spec.id for spec in cfg.searchers if spec.enabled}
    assert {"ddg", "tavily", "exa"} <= enabled
    order = cfg.crawl.crawler_order
    assert "playwright" in order
    assert "crawlee" in order
    assert order.index("playwright") < order.index("crawlee")


def test_crawler_failover_httpx_to_playwright(monkeypatch: pytest.MonkeyPatch) -> None:
    """When httpx fails, the yaml order falls through to the Playwright fetcher."""
    calls: list[str] = []

    def broken_httpx(url: str, **kwargs: object) -> bytes:
        calls.append("httpx")
        raise OSError("httpx down")

    def fake_playwright(url: str, **kwargs: object) -> bytes:
        calls.append("playwright")
        return b"<html>js-rendered</html>"

    monkeypatch.setattr(crawl_mod, "default_fetch", broken_httpx)
    monkeypatch.setattr(crawl_mod, "fetch_playwright", fake_playwright)
    spec = CrawlSpec(crawler_order=("httpx", "playwright"), timeout_s=1.0)

    body, used = ordered_fetch("https://example.com/page", crawl=spec)
    assert body == b"<html>js-rendered</html>"
    assert used == "playwright"
    assert calls == ["httpx", "playwright"]


def test_crawler_failover_playwright_to_crawlee(monkeypatch: pytest.MonkeyPatch) -> None:
    """Playwright failing (e.g. browser missing) falls through to Crawlee."""
    calls: list[str] = []

    def broken_playwright(url: str, **kwargs: object) -> bytes:
        calls.append("playwright")
        raise OSError("playwright not installed")

    def fake_crawlee(url: str, **kwargs: object) -> bytes:
        calls.append("crawlee")
        return b"<html>crawlee body</html>"

    monkeypatch.setattr(crawl_mod, "fetch_playwright", broken_playwright)
    monkeypatch.setattr(crawl_mod, "fetch_crawlee", fake_crawlee)
    spec = CrawlSpec(crawler_order=("playwright", "crawlee"), timeout_s=1.0)

    body, used = ordered_fetch("https://example.com/page", crawl=spec)
    assert body == b"<html>crawlee body</html>"
    assert used == "crawlee"
    assert calls == ["playwright", "crawlee"]


def test_crawler_prefers_httpx_when_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    """A healthy httpx short-circuits: playwright/crawlee never run."""

    def fake_httpx(url: str, **kwargs: object) -> bytes:
        return b"<html>static</html>"

    def must_not_run(url: str, **kwargs: object) -> bytes:
        raise AssertionError("JS crawler ran although httpx succeeded")

    monkeypatch.setattr(crawl_mod, "default_fetch", fake_httpx)
    monkeypatch.setattr(crawl_mod, "fetch_playwright", must_not_run)
    monkeypatch.setattr(crawl_mod, "fetch_crawlee", must_not_run)
    spec = CrawlSpec(crawler_order=("httpx", "playwright", "crawlee"), timeout_s=1.0)

    body, used = ordered_fetch("https://example.com/page", crawl=spec)
    assert body == b"<html>static</html>"
    assert used == "httpx"


def test_crawlee_start_uses_canonical_unique_key() -> None:
    """JS uniqueKey / Python unique_key drop tracking params via normalize_url."""

    class FakeRequest:
        @classmethod
        def from_url(cls, url: str, *, unique_key: str | None = None) -> dict[str, str | None]:
            return {"url": url, "unique_key": unique_key}

    raw = "https://Example.com/docs/Page?utm_source=crawlee&a=1"
    queued = crawlee_start(raw, FakeRequest)
    assert queued == [{"url": raw, "unique_key": "https://example.com/docs/Page?a=1"}]
    assert crawlee_start(raw, None) == [raw]


@pytest.mark.parametrize("engine", ["stdio", "uvx"])
def test_ddg_mcp_local_spawn_is_ready_without_url(
    engine: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """engine: stdio/uvx pass the readiness gate even with DDG_MCP_URL unset."""
    monkeypatch.delenv("DDG_MCP_URL", raising=False)
    spec = SearcherSpec(id="ddg_mcp", kind="websearcher", engine=engine, base_url_env="DDG_MCP_URL")
    config = ProvidersConfig(version=1, searchers=(spec,))

    def backend(q: str, s: SearcherSpec) -> list[SearchHit]:
        return [_hit("DDG MCP", "https://ddg-mcp.example/", "ddg_mcp")]

    result = search("query", config=config, backends={"ddg_mcp": backend}, cache_ttl_s=0)
    assert result.status["ddg_mcp"].status == "ok", result.status["ddg_mcp"].hint
    assert len(result.hits) == 1


def test_search_ddg_mcp_parses_numbered_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """The python server's ``{"result": "1. title / URL / Summary"}`` text becomes hits."""
    payload = {
        "result": (
            "Found 1 search result:\n\n"
            "1. LangGraph docs\n"
            "   URL: https://langchain.github.io/langgraph/\n"
            "   Summary: Low-level orchestration framework.\n"
        )
    }

    async def fake_search(target: object, query: str) -> object:
        return payload

    monkeypatch.setenv("DDG_MCP_URL", "http://127.0.0.1:9999/mcp")
    monkeypatch.setattr(providers_mod, "_ddg_mcp_search", fake_search)
    spec = SearcherSpec(id="ddg_mcp", kind="websearcher", base_url_env="DDG_MCP_URL")

    hits = providers_mod.search_ddg_mcp("langgraph", spec)
    assert [h.url for h in hits] == ["https://langchain.github.io/langgraph/"]
    assert hits[0].title == "LangGraph docs"
    assert "orchestration" in hits[0].snippet


def test_fetch_ddg_mcp_returns_page_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """fetch_ddg_mcp surfaces the MCP fetch_content tool's text."""

    async def fake_fetch(target: object, url: str) -> object:
        assert url == "https://example.com/page"
        return "cleaned page text"

    monkeypatch.setenv("DDG_MCP_URL", "http://127.0.0.1:9999/mcp")
    monkeypatch.setattr(providers_mod, "_ddg_mcp_fetch", fake_fetch)
    assert providers_mod.fetch_ddg_mcp("https://example.com/page") == "cleaned page text"


def test_fetch_ddg_mcp_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A dead MCP server yields empty text, never an exception."""

    async def broken_fetch(target: object, url: str) -> object:
        raise OSError("server down")

    monkeypatch.setenv("DDG_MCP_URL", "http://127.0.0.1:9999/mcp")
    monkeypatch.setattr(providers_mod, "_ddg_mcp_fetch", broken_fetch)
    assert providers_mod.fetch_ddg_mcp("https://example.com/page") == ""


_YOU_PAYLOAD = {
    "results": {
        "web": [
            {
                "url": "https://langchain.github.io/langgraph/",
                "title": "LangGraph",
                "description": "Low-level orchestration for multi-agent systems.",
                "snippets": ["ignored when description is present"],
            },
            {
                "url": "https://docs.example/snippets-only",
                "title": "Snippets only",
                "snippets": ["First snippet.", "Second snippet."],
            },
            {"url": "ftp://bad.example/", "title": "bad scheme"},
        ]
    },
    "metadata": {"query": "langgraph", "latency": 0.4},
}


def test_search_you_parses_results_web(monkeypatch: pytest.MonkeyPatch) -> None:
    """You.com results.web rows become SearchHits; description wins over snippets."""
    captured: dict[str, object] = {}

    def fake_call_json(method: str, url: str, **kwargs: object) -> object:
        captured["method"] = method
        captured["url"] = url
        captured["body"] = kwargs.get("json_body")
        return _YOU_PAYLOAD

    monkeypatch.setenv("YOU_API_KEY", "test-key")
    monkeypatch.setattr(providers_mod, "call_json", fake_call_json)
    spec = SearcherSpec(id="you", kind="websearcher", api_key_env="YOU_API_KEY")

    hits = providers_mod.search_you("langgraph", spec)

    assert captured["method"] == "POST"
    assert captured["url"] == "https://ydc-index.io/v1/search"
    assert [h.url for h in hits] == [
        "https://langchain.github.io/langgraph/",
        "https://docs.example/snippets-only",
    ]
    assert hits[0].snippet.startswith("Low-level orchestration")
    assert hits[1].snippet == "First snippet. Second snippet."
    assert all(h.searcher_id == "you" for h in hits)


def test_search_you_fails_closed_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """No YOU_API_KEY: no HTTP call, empty hits."""
    monkeypatch.delenv("YOU_API_KEY", raising=False)
    called: list[str] = []
    monkeypatch.setattr(providers_mod, "call_json", lambda *a, **k: called.append("http") or None)
    spec = SearcherSpec(id="you", kind="websearcher", api_key_env="YOU_API_KEY")
    assert providers_mod.search_you("langgraph", spec) == []
    assert called == []


def test_search_minimax_parses_web_search_tool_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """MiniMax Anthropic-style web_search_tool_result blocks become SearchHits."""
    payload = {
        "content": [
            {"type": "text", "text": "Let me search."},
            {
                "type": "web_search_tool_result",
                "tool_use_id": "call_1",
                "content": [
                    {
                        "type": "web_search_result",
                        "title": "LangGraph",
                        "url": "https://langchain.github.io/langgraph/",
                        "content": "Low-level orchestration framework.",
                    },
                    {"type": "web_search_result", "title": "no-url-row"},
                ],
            },
        ]
    }

    def fake_call_json(method: str, url: str, **kwargs: object) -> object:
        assert url == "https://api.minimax.io/anthropic/v1/messages"
        return payload

    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    monkeypatch.setattr(providers_mod, "call_json", fake_call_json)
    spec = SearcherSpec(id="minimax", kind="websearcher", api_key_env="MINIMAX_API_KEY")

    hits = providers_mod.search_minimax("langgraph", spec)
    assert [h.url for h in hits] == ["https://langchain.github.io/langgraph/"]
    assert hits[0].snippet.startswith("Low-level orchestration")


def test_search_minimax_fails_closed_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """No MINIMAX_API_KEY: no HTTP call, empty hits."""
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    called: list[str] = []
    monkeypatch.setattr(providers_mod, "call_json", lambda *a, **k: called.append("http") or None)
    spec = SearcherSpec(id="minimax", kind="websearcher", api_key_env="MINIMAX_API_KEY")
    assert providers_mod.search_minimax("langgraph", spec) == []
    assert called == []


def test_zread_and_minimax_ship_disabled() -> None:
    """Packaged registry ships zread and minimax add-but-disabled."""
    by_id = {spec.id: spec for spec in load_providers().searchers}
    assert by_id["zread"].enabled is False
    assert by_id["zread"].base_url_env == "ZREAD_MCP_URL"
    assert by_id["minimax"].enabled is False
    assert by_id["minimax"].api_key_env == "MINIMAX_API_KEY"
    assert "minimax" in builtin_searchers_ids()
    assert "zread" in builtin_searchers_ids()


def builtin_searchers_ids() -> set[str]:
    """Registered builtin searcher ids."""
    from WebSearch.frontend.fanout import builtin_searchers

    return set(builtin_searchers())
