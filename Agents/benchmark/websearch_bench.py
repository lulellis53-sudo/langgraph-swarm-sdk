"""WebSearch benchmark: one query, every searcher, one row per tool.

Per tool: sites that appeared, sites scraped, normalization %, tokens used and
time. Definitions (all measured, none estimated):

* ``appeared``  unique canonical URLs the tool returned.
* ``scraped``   pages fetched without error and with a non-empty body.
* ``norm_pct``  ``100 * (1 - normalized_chars / raw_html_chars)`` over scraped pages.
* ``tokens``    ``count_text`` (tiktoken ``cl100k_base``) of the normalized text
  that would be injected into a prompt.
* ``api_tokens`` tokens the search API itself reported (Google grounding only).
* ``search_ms`` / ``scrape_ms``  wall time of the search call and of scraping its hits.

Run live (needs the tool's env key; tools without a key report zeros)::

    uv run python -m benchmark.websearch_bench --query "(a|b) AND (c) after:2026-03-01"
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from WebSearch import (
    FetchFn,
    ProvidersConfig,
    SearchFn,
    SearchHit,
    builtin_searchers,
    crawl_then_scrape,
    load_providers,
)
from WebSearch.backend import dedupe_docs, extract_and_normalize
from WebSearch.frontend.models import dedupe_hits

from swarm_sdk.prompting.budget import count_text

RESULTS_DIR = Path(__file__).parent / "results" / "websearch_tools"


@dataclass(frozen=True, slots=True)
class ToolRow:
    tool: str
    appeared: int
    scraped: int
    norm_pct: float
    tokens: int
    api_tokens: int
    search_ms: float
    scrape_ms: float


def _bench_tool(
    tool: str,
    fn: SearchFn,
    query: str,
    cfg: ProvidersConfig,
    fetch: FetchFn | None,
) -> tuple[ToolRow, list[SearchHit]]:
    spec = next(s for s in cfg.searchers if s.id == tool)
    t0 = time.perf_counter()
    try:
        raw_hits = list(fn(query, spec))
    except TimeoutError, OSError, ConnectionError, ValueError:
        raw_hits = []
    search_ms = (time.perf_counter() - t0) * 1000
    hits = dedupe_hits(raw_hits)

    t1 = time.perf_counter()
    pages = crawl_then_scrape(hits, fetch=fetch, config=cfg)
    docs = dedupe_docs(
        extract_and_normalize(p.html, url=p.url, config=cfg) for p in pages if p.html
    )
    scrape_ms = (time.perf_counter() - t1) * 1000

    raw_chars = sum(d.raw_chars for d in docs)
    norm_chars = sum(len(d.text) for d in docs)
    row = ToolRow(
        tool=tool,
        appeared=len(hits),
        scraped=sum(1 for p in pages if p.html and p.error is None),
        norm_pct=round(100 * (1 - norm_chars / raw_chars), 1) if raw_chars else 0.0,
        tokens=sum(count_text(d.text) for d in docs),
        api_tokens=sum(h.api_tokens for h in raw_hits),
        search_ms=round(search_ms, 1),
        scrape_ms=round(scrape_ms, 1),
    )
    return row, hits


def run_benchmark(
    query: str,
    *,
    backends: Mapping[str, SearchFn] | None = None,
    fetch: FetchFn | None = None,
    config: ProvidersConfig | None = None,
) -> dict[str, Any]:
    """Run *query* on every backend concurrently and score each tool.

    Args:
        query (str): The single query sent to all tools.
        backends (Mapping[str, SearchFn] | None): id → search fn; default HTTP APIs.
        fetch (FetchFn | None): URL GET override (tests); default real crawlers.
        config (ProvidersConfig | None): Registry; default from yaml.

    Returns:
        dict[str, object]: ``rows`` (one per tool) and ``merged`` cross-tool dedupe stats.
    """
    cfg = config or load_providers()
    table = dict(builtin_searchers() if backends is None else backends)
    tools = [s.id for s in cfg.searchers if s.id in table]
    if not tools:
        return {"query": query, "rows": [], "merged": {"raw": 0, "unique": 0, "duplicates": 0}}
    with ThreadPoolExecutor(max_workers=len(tools)) as pool:
        results = list(pool.map(lambda t: _bench_tool(t, table[t], query, cfg, fetch), tools))
    all_hits = [h for _, hits in results for h in hits]
    unique = len(dedupe_hits(all_hits))
    return {
        "query": query,
        "rows": [asdict(row) for row, _ in results],
        "merged": {
            "raw": len(all_hits),
            "unique": unique,
            "duplicates": len(all_hits) - unique,
        },
    }


def format_table(report: Mapping[str, Any]) -> str:
    """Render a report from :func:`run_benchmark` as a fixed-width table."""
    cols = (
        "tool",
        "appeared",
        "scraped",
        "norm_pct",
        "tokens",
        "api_tokens",
        "search_ms",
        "scrape_ms",
    )
    rows = report["rows"]
    lines = [" ".join(f"{c:>12}" for c in cols)]
    lines += [" ".join(f"{row[c]:>12}" for c in cols) for row in rows]
    merged = report["merged"]
    lines.append(
        f"merged: {merged['raw']} hits -> {merged['unique']} unique "
        f"({merged['duplicates']} duplicates removed)"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark WebSearch tools on one query")
    parser.add_argument("--query", required=True)
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    parser.add_argument("--write-results", action="store_true")
    args = parser.parse_args(argv)
    report = run_benchmark(args.query)
    print(json.dumps(report, indent=2) if args.json else format_table(report))
    if args.write_results:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        out = RESULTS_DIR / f"{int(time.time())}.json"
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
