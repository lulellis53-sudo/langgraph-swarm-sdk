"""CI-sized check: the 3-agent pipeline fetches, dedupes, and stores."""

from __future__ import annotations

from pathlib import Path

from WebSearch.backend.store import connect, count_documents
from WebSearch.browser_agent import run_cowork_pipeline

PAGES = {
    "https://a.example/x": (
        "<html><body><h1>Alpha Page</h1><p>Unique alpha content.</p></body></html>"
    ),
    "https://b.example/y": (
        "<html><body><h1>Beta Page</h1><p>Different beta content.</p></body></html>"
    ),
    "https://c.example/z": (
        "<html><body><h1>Alpha Page</h1><p>Unique alpha content.</p></body></html>"
    ),
}
ORDER = ["https://a.example/x", "https://b.example/y", "https://c.example/z"]


def test_pipeline_fetches_dedupes_and_stores(tmp_path: Path) -> None:
    calls: list[str] = []

    def fake_fetch(url: str) -> bytes:
        calls.append(url)
        return PAGES[url].encode("utf-8")

    db = tmp_path / "docs.db"
    report = run_cowork_pipeline(
        ORDER, fetch=fake_fetch, db_path=db, max_concurrency=3
    )

    assert sorted(calls) == ORDER  # one fetch step per URL
    assert report["fetched"] == 3
    assert report["docs"] == 2  # c.example duplicates a.example content
    assert report["stored"] == 2
    conn = connect(db)
    assert count_documents(conn) == 2
    conn.close()


def test_pipeline_dedupes_urls_before_fetch(tmp_path: Path) -> None:
    calls: list[str] = []

    def fake_fetch(url: str) -> bytes:
        calls.append(url)
        return b"<html><body>once</body></html>"

    report = run_cowork_pipeline(
        ["https://d.example/1", "https://d.example/1"],
        fetch=fake_fetch,
        db_path=tmp_path / "docs.db",
    )
    assert calls == ["https://d.example/1"]
    assert report["fetched"] == 1
    assert report["stored"] == 1
