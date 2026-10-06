"""WebSearch pipeline layout tests (no network)."""

from __future__ import annotations

from WebSearch import run_pipeline
from WebSearch.backend import extract_and_normalize, normalize_text
from WebSearch.frontend import (
    ProvidersConfig,
    SearcherSpec,
    SearchHit,
    get_searcher,
    load_providers,
    parallel_search,
    registry_search,
    search_brave,
    search_tavily,
    searcher_ids,
)
from WebSearch.frontend.websearchers import search_kimi
from WebSearch.midend import crawl_then_scrape
from WebSearch.repeater import repeater


def test_load_providers_yaml() -> None:
    cfg = load_providers()
    assert cfg.extractor_order == (
        "selectolax",
        "selectolax_regex",
        "regex",
        "trafilatura",
        "bs4",
    )
    assert cfg.crawl.crawler_order == ("httpx", "curl_cffi", "scrapy", "playwright", "crawlee")
    assert searcher_ids(cfg) == (
        "context7",
        "brave",
        "ddg",
        "ddglite",
        "tavily",
        "jina",
        "apify",
        "openrouter_web",
        "exa",
        "bright_data",
        "searxng",
        "google_ground",
        "kimisearch",
    )
    assert get_searcher(cfg, "tavily").api_key_env == "TAVILY_API_KEY"
    assert get_searcher(cfg, "exa").api_key_env == "EXA_API_KEY"
    assert get_searcher(cfg, "brave").api_key_env == "BRAVE_API_KEY"
    assert get_searcher(cfg, "bright_data").api_key_env == "BRIGHTDATA_MCP_TOKEN"
    assert get_searcher(cfg, "searxng").engine == "duckduckgo,bing"
    assert "https" in cfg.crawl.schemes


def test_http_apis_fail_closed_without_keys() -> None:
    spec = SearcherSpec(id="brave", kind="websearcher", api_key_env="BRAVE_API_KEY")
    assert search_brave("q", spec) == []
    spec_t = SearcherSpec(id="tavily", kind="websearcher", api_key_env="TAVILY_API_KEY")
    assert search_tavily("q", spec_t) == []


def test_kimisearch_spec_is_in_registry() -> None:
    cfg = load_providers()
    spec = get_searcher(cfg, "kimisearch")
    assert spec.api_key_env == "MOONSHOT_API_KEY"
    assert spec.base_url_env == "MOONSHOT_BASE_URL"
    assert spec.engine == "kimi-k3"


def test_jina_parses_search_foundation_response(monkeypatch) -> None:
    from WebSearch.frontend import websearchers

    captured: dict[str, object] = {}

    def fake_httpx_json(method: str, url: str, **kwargs: object) -> dict[str, object]:
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        captured["body"] = kwargs.get("json_body")
        return {
            "data": [
                {
                    "title": "Jina",
                    "url": "https://jina.ai",
                    "content": "x" * 400,
                    "usage": {"tokens": 12},
                }
            ]
        }

    monkeypatch.setenv("JINA_API_KEY", "k")
    monkeypatch.setattr(websearchers, "_httpx_json", fake_httpx_json)
    hits = websearchers.search_jina(
        "q", SearcherSpec(id="jina", kind="websearcher", api_key_env="JINA_API_KEY")
    )
    assert captured["method"] == "POST"
    assert captured["url"] == "https://s.jina.ai/"
    assert captured["body"] == {"q": "q", "num": 8}
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer k"
    assert headers["Accept"] == "application/json"
    assert hits[0].title == "Jina"
    assert hits[0].url == "https://jina.ai"
    assert hits[0].snippet == "x" * 280
    assert hits[0].api_tokens == 12
    monkeypatch.delenv("JINA_API_KEY")
    assert (
        websearchers.search_jina(
            "q", SearcherSpec(id="jina", kind="websearcher", api_key_env="JINA_API_KEY")
        )
        == []
    )


def test_kimisearch_fails_closed_without_key() -> None:
    spec = SearcherSpec(id="kimisearch", kind="websearcher", api_key_env="KIMI_MISSING_KEY")
    assert search_kimi("q", spec) == []


def test_kimisearch_parses_web_search_basic_response(monkeypatch) -> None:
    from WebSearch.frontend import websearchers

    payload = {
        "search_results": [
            {"title": "A", "url": "https://a.example", "snippet": "snippet a"},
            {"title": "B", "url": "https://b.example", "snippet": "snippet b"},
        ]
    }
    monkeypatch.setenv("MOONSHOT_API_KEY", "k")
    monkeypatch.setattr(websearchers, "_httpx_json", lambda *a, **k: payload)
    spec = SearcherSpec(id="kimisearch", kind="websearcher", api_key_env="MOONSHOT_API_KEY")
    hits = search_kimi("q", spec)
    assert [h.title for h in hits] == ["A", "B"]
    assert hits[0].url == "https://a.example"
    assert hits[0].snippet == "snippet a"
    assert hits[0].searcher_id == "kimisearch"


def test_kimisearch_translates_dork_to_sites_and_time_window(monkeypatch) -> None:
    from WebSearch.frontend import websearchers

    captured: dict[str, object] = {}

    def fake_httpx_json(method: str, url: str, *, json_body: dict[str, object], **kwargs: object):
        captured["url"] = url
        captured["body"] = json_body
        return {"search_results": []}

    monkeypatch.setenv("MOONSHOT_API_KEY", "k")
    monkeypatch.setattr(websearchers, "_httpx_json", fake_httpx_json)
    spec = SearcherSpec(
        id="kimisearch",
        kind="websearcher",
        api_key_env="MOONSHOT_API_KEY",
        dork="translate",
    )
    search_kimi("site:example.com after:2026-01-01 before:2026-12-31 q", spec)
    body = captured["body"]
    assert body["sites"] == ["example.com"]
    assert body["time_window"] == {"start": "2026-01-01", "end": "2026-12-31"}


def test_parallel_search_catches_oserror_from_a_provider() -> None:
    def ok(query: str, spec: SearcherSpec) -> list[SearchHit]:
        return [SearchHit("OK", "https://ok.example/", "", spec.id)]

    def boom(query: str, spec: SearcherSpec) -> list[SearchHit]:
        raise OSError("simulated failure")

    hits = parallel_search("q", backends={"ok": ok, "failing": boom})
    assert [h.title for h in hits] == ["OK"]


def test_registry_search_injected_backend() -> None:
    def backend(query: str, spec: SearcherSpec) -> list[SearchHit]:
        del query
        return [
            SearchHit(
                title="Example",
                url="https://example.com/page",
                snippet="hello",
                searcher_id=spec.id,
            )
        ]

    hits = registry_search("q", backends={"bright_data": backend}, searcher_id="bright_data")
    assert len(hits) == 1
    assert hits[0].url.startswith("https://")


def test_registry_search_failover_empty() -> None:
    def empty(query: str, spec: SearcherSpec) -> list[SearchHit]:
        del query, spec
        return []

    def ok(query: str, spec: SearcherSpec) -> list[SearchHit]:
        del query
        return [SearchHit("t", "https://example.com/", "", spec.id)]

    hits = registry_search(
        "q",
        backends={"brave": empty, "tavily": ok},
        searcher_id=None,
    )
    assert hits and hits[0].searcher_id == "tavily"


def test_midend_blocks_non_http_and_scrapes() -> None:
    hits = [
        SearchHit("a", "file:///tmp/x", "", "tavily"),
        SearchHit("b", "https://example.com/ok", "", "tavily"),
    ]

    def fetch(url: str) -> bytes:
        assert url.startswith("https://")
        return b"<html><body><p>Hello   world</p></body></html>"

    pages = crawl_then_scrape(hits, fetch=fetch)
    assert pages[0].error == "blocked_scheme"
    assert "Hello" in pages[1].html


def test_backend_regex_and_normalize() -> None:
    assert normalize_text("  a\n\tb  ") == "a b"
    html = "<html><script>secret</script><body><h1>Title</h1><p>Para</p></body></html>"
    doc = extract_and_normalize(html, url="https://example.com")
    assert "Title" in doc.text
    assert "Para" in doc.text
    if doc.extractor != "fallback":
        assert "secret" not in doc.text
    from WebSearch.frontend import CrawlSpec, ProvidersConfig

    regex_cfg = ProvidersConfig(
        version=1,
        searchers=(),
        extractor_order=("regex",),
        crawl=CrawlSpec(),
    )
    regex_doc = extract_and_normalize(html, url="https://example.com", config=regex_cfg)
    assert regex_doc.extractor == "regex"
    assert "Title" in regex_doc.text


def test_repeater_retries_then_raises() -> None:
    n = {"i": 0}

    @repeater.s
    def boom() -> int:
        n["i"] += 1
        raise OSError("nope")

    try:
        boom()
    except OSError:
        pass
    else:
        raise AssertionError("expected OSError")
    assert n["i"] == 2


def test_run_pipeline_end_to_end() -> None:
    def backend(query: str, spec: SearcherSpec) -> list[SearchHit]:
        del query
        return [SearchHit("t", "https://example.com/x", "s", spec.id)]

    def fetch(url: str) -> bytes:
        del url
        return b"<html><body><p>Alpha  beta</p></body></html>"

    hits, pages, docs = run_pipeline(
        "q",
        backends={"tavily": backend},
        fetch=fetch,
        searcher_id="tavily",
    )
    assert hits and pages and docs
    assert docs[0].text == "Alpha beta"


def test_parallel_search_merges_and_dedupes() -> None:
    from WebSearch import parallel_search

    def a(query: str, spec: SearcherSpec) -> list[SearchHit]:
        return [SearchHit("A", "https://www.Example.com/p/?utm_source=x#frag", "", spec.id)]

    def b(query: str, spec: SearcherSpec) -> list[SearchHit]:
        return [
            SearchHit("B", "https://example.com/p", "", spec.id),
            SearchHit("B2", "https://example.com/q", "", spec.id),
        ]

    def boom(query: str, spec: SearcherSpec) -> list[SearchHit]:
        raise TimeoutError

    hits = parallel_search("q", backends={"brave": a, "tavily": b, "exa": boom})
    assert [h.title for h in hits] == ["A", "B2"]
    assert hits[0].searcher_id == "brave"


def test_parallel_search_runs_concurrently() -> None:
    import threading

    from WebSearch import parallel_search

    barrier = threading.Barrier(2, timeout=5)

    def waits(query: str, spec: SearcherSpec) -> list[SearchHit]:
        barrier.wait()  # only passes if both searchers run at the same time
        return [SearchHit("t", f"https://example.com/{spec.id}", "", spec.id)]

    hits = parallel_search("q", backends={"brave": waits, "tavily": waits})
    assert len(hits) == 2


def test_parallel_search_ranks_consensus_first() -> None:
    from WebSearch import parallel_search

    def brave(query: str, spec: SearcherSpec) -> list[SearchHit]:
        return [
            SearchHit("X", "https://x.example/", "", spec.id),
            SearchHit("B", "https://b.example/", "", spec.id),
        ]

    def tavily(query: str, spec: SearcherSpec) -> list[SearchHit]:
        return [
            SearchHit("B", "https://B.example/", "", spec.id),
            SearchHit("Y", "https://y.example/", "", spec.id),
        ]

    fused = parallel_search("q", backends={"brave": brave, "tavily": tavily})
    assert [h.title for h in fused] == ["B", "X", "Y"]

    unfused = parallel_search("q", backends={"brave": brave, "tavily": tavily}, fuse=False)
    assert [h.title for h in unfused] == ["X", "B", "Y"]


def test_parallel_search_timeout_abandons_slow_provider() -> None:
    import time

    from WebSearch import parallel_search

    def slow(query: str, spec: SearcherSpec) -> list[SearchHit]:
        time.sleep(1.0)
        return [SearchHit("S", "https://slow.example/", "", spec.id)]

    def fast(query: str, spec: SearcherSpec) -> list[SearchHit]:
        return [SearchHit("F", "https://fast.example/", "", spec.id)]

    started = time.perf_counter()
    hits = parallel_search("q", backends={"brave": slow, "tavily": fast}, timeout_s=0.1)
    elapsed = time.perf_counter() - started
    assert [h.title for h in hits] == ["F"]
    assert elapsed < 0.8


def test_parallel_search_limit_caps_results() -> None:
    from WebSearch import parallel_search

    def many(query: str, spec: SearcherSpec) -> list[SearchHit]:
        return [SearchHit(f"T{i}", f"https://limit.example/{i}", "", spec.id) for i in range(5)]

    assert len(parallel_search("q", backends={"brave": many}, limit=2)) == 2
    assert len(parallel_search("q", backends={"brave": many})) == 5


def test_search_brief_is_numbered_normalized_and_capped() -> None:
    from WebSearch import search_brief

    def brave(query: str, spec: SearcherSpec) -> list[SearchHit]:
        return [
            SearchHit(
                "Alpha  <b>Beta</b>\nMenu\nmenu",
                "https://x.example/a?utm_source=t#frag",
                "line1\nline1\n  line2 ",
                spec.id,
            )
        ]

    def tavily(query: str, spec: SearcherSpec) -> list[SearchHit]:
        return [
            SearchHit("Alpha Beta", "https://x.example/a", "dup", spec.id),
            SearchHit("Gamma", "https://y.example/", "g", spec.id),
        ]

    brief = search_brief("q", backends={"brave": brave, "tavily": tavily})
    assert "[1]" in brief and "[2]" in brief
    assert "Alpha Beta" in brief
    assert "<b>" not in brief
    assert "line1 line2" in brief
    assert "menu menu" not in brief
    assert "utm_source" not in brief and "#frag" not in brief
    assert "Sources: brave, tavily" in brief

    short = search_brief("q", backends={"brave": brave, "tavily": tavily}, max_chars=40)
    assert len(short.splitlines()) < len(brief.splitlines())


def test_render_brief_empty_hits() -> None:
    from WebSearch import render_brief

    assert render_brief([]) == ""


def test_dork_builder() -> None:
    import pytest
    from WebSearch.frontend import DorkError, any_of, dork

    assert any_of("a", "two words") == '(a|"two words")'
    assert (
        dork(["api", "token"], ["leak", "exposed"], after="2026-01-15", filetype="pdf")
        == "(api|token) AND (leak|exposed) filetype:pdf after:2026-01-15"
    )
    with pytest.raises(DorkError):
        dork(["a"], after="2026-13-01")
    with pytest.raises(DorkError):
        dork(["a|b"])
    with pytest.raises(DorkError):
        dork(["a"], after="2026-05-02", before="2026-05-01")


def test_google_ground_parses_chunks_and_tokens(monkeypatch) -> None:
    from WebSearch import frontend
    from WebSearch.frontend import websearchers

    payload = {
        "candidates": [
            {
                "groundingMetadata": {
                    "groundingChunks": [
                        {"web": {"uri": "https://r.example/a", "title": "a.com"}},
                        {"web": {"uri": "https://r.example/b", "title": "b.com"}},
                    ],
                    "groundingSupports": [
                        {"segment": {"text": "claim"}, "groundingChunkIndices": [1]}
                    ],
                }
            }
        ],
        "usageMetadata": {"totalTokenCount": 42},
    }
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(websearchers, "request_json", lambda *a, **k: payload)
    spec = SearcherSpec(id="google_ground", kind="websearcher", api_key_env="GEMINI_API_KEY")
    hits = frontend.search_google_ground("q", spec)
    assert [h.title for h in hits] == ["a.com", "b.com"]
    assert hits[1].snippet == "claim"
    assert (hits[0].api_tokens, hits[1].api_tokens) == (42, 0)
    monkeypatch.delenv("GEMINI_API_KEY")
    monkeypatch.setattr(websearchers, "_keychain_secret", lambda name: "")
    assert frontend.search_google_ground("q", spec) == []


def test_normalize_dedupes_lines_and_entities() -> None:
    from WebSearch.backend import ExtractedDoc, dedupe_docs

    assert normalize_text("Menu\nHome\nmenu\nA&amp;B​\nCafé x") == "Menu Home A&B Café x"
    a = ExtractedDoc("Same text", "regex", "https://a")
    b = ExtractedDoc("same TEXT", "regex", "https://b")
    assert dedupe_docs([a, b, ExtractedDoc("", "regex")]) == [a]


def test_midend_dedupes_urls_before_cap() -> None:
    hits = [
        SearchHit("a", "https://example.com/x?utm_source=t", "", "s"),
        SearchHit("b", "https://www.example.com/x/", "", "s"),
        SearchHit("c", "https://example.com/y", "", "s"),
    ]
    pages = crawl_then_scrape(hits, fetch=lambda u: b"<p>hi</p>")
    assert [p.url for p in pages] == [hits[0].url, hits[2].url]


def test_langchain_tools_use_injected_backend() -> None:
    from WebSearch.langchain_tools import websearch_langchain_tools

    def backend(query: str, spec: SearcherSpec) -> list[SearchHit]:
        del query
        return [
            SearchHit(
                title="LC",
                url="https://example.com/lc",
                snippet="from tool",
                searcher_id=spec.id,
            )
        ]

    cfg = ProvidersConfig(
        version=1,
        searchers=(SearcherSpec(id="stub", kind="websearcher"),),
        extractor_order=("regex",),
    )
    tools = websearch_langchain_tools(config=cfg, backends={"stub": backend})
    by_name = {tool.name: tool for tool in tools}
    brief = by_name["web_search_brief"].invoke({"query": "q", "limit": 3})
    assert "LC" in brief and "example.com/lc" in brief
    payload = by_name["web_search_hits"].invoke({"query": "q", "limit": 3})
    assert payload[0]["title"] == "LC" and payload[0]["searcher_id"] == "stub"
