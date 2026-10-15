"""Metasearch utility tests; no requests leave the test process."""

import asyncio

from langswarm import websearch


def test_metasearch_merges_same_url_and_reports_engine_errors(monkeypatch) -> None:
    def fake_engine(engine: str, query: str, limit: int) -> list[websearch.SearchResult]:
        if engine == "broken":
            raise RuntimeError("offline")
        return [websearch.SearchResult("title", "https://example.com/a", engine, [engine])]

    monkeypatch.setattr(websearch, "_search_engine", fake_engine)
    results, errors = asyncio.run(websearch._run("query", ["bing", "wikipedia", "broken"], 5))
    assert len(results) == 1
    assert results[0].engines == ["bing", "wikipedia"]
    assert errors == ["broken: offline"]
