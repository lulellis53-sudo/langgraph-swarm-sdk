"""Offline check of the per-tool WebSearch metrics (no network, no keys)."""

from __future__ import annotations

from benchmark.websearch_bench import format_table, run_benchmark
from WebSearch import SearchHit
from WebSearch.frontend import SearcherSpec

_PAGE = (
    b"<html><script>var x=1;</script><body><nav>Home</nav><nav>home</nav>"
    b"<p>Alpha beta gamma</p></body></html>"
)


def _tool(*urls: str, tokens: int = 0):
    def fn(query: str, spec: SearcherSpec) -> list[SearchHit]:
        return [SearchHit(u, u, "", spec.id, tokens if i == 0 else 0) for i, u in enumerate(urls)]

    return fn


def test_per_tool_rows_and_merged_dedupe() -> None:
    report = run_benchmark(
        "q",
        backends={
            "brave": _tool("https://a.com/1", "https://www.a.com/1/", "https://b.com/2"),
            "google_ground": _tool("https://a.com/1", tokens=42),
        },
        fetch=lambda url: _PAGE,
    )
    rows = {r["tool"]: r for r in report["rows"]}
    assert rows["brave"]["appeared"] == 2  # in-tool duplicate collapsed
    assert rows["google_ground"]["api_tokens"] == 42
    assert rows["brave"]["scraped"] == 2
    assert rows["brave"]["tokens"] > 0
    assert 0 < rows["brave"]["norm_pct"] < 100
    assert report["merged"] == {"raw": 3, "unique": 2, "duplicates": 1}
    assert "brave" in format_table(report)


def test_no_backends_gives_empty_report() -> None:
    assert run_benchmark("q", backends={})["rows"] == []
