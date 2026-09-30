"""WebSearch pipeline layout tests (no network)."""

from __future__ import annotations

from WebSearch import run_pipeline
from WebSearch.backend import extract_and_normalize, normalize_text
from WebSearch.frontend.providers import SearcherSpec, get_searcher, load_providers
from WebSearch.frontend.websearchers import SearchHit, registry_search, searcher_ids
from WebSearch.midend import crawl_then_scrape


def test_load_providers_yaml() -> None:
    cfg = load_providers()
    assert cfg.extractor_order == ("selectolax", "trafilatura", "bs4")
    assert searcher_ids(cfg) == ("context7", "bright_data", "tavily")
    assert get_searcher(cfg, "tavily").api_key_env == "TAVILY_API_KEY"
    assert "https" in cfg.crawl.schemes


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


def test_backend_normalize_and_extract() -> None:
    assert normalize_text("  a\n\tb  ") == "a b"
    doc = extract_and_normalize(
        "<html><script>secret</script><body><h1>Title</h1><p>Para</p></body></html>",
        url="https://example.com",
    )
    assert "Title" in doc.text
    assert "Para" in doc.text
    if doc.extractor != "fallback":
        assert "secret" not in doc.text


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
