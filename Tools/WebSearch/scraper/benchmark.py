"""Benchmark harness for the WebScraper hit pipeline.

Measures, on synthetic data (no network, no model downloads):

- ``bench_pack_hits``: token-saver throughput and savings percentage.
- ``bench_dedupe_quality``: how many near-duplicates a noisy hit list loses.
- ``bench_estimate_tokens``: estimator throughput (tokens/sec).

Run: ``PYTHONPATH=. python -m WebSearch.scraper.benchmark``
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any

from WebSearch.scraper.tokensaver import estimate_tokens, pack_hits, savings_report

__all__ = ["BenchResult", "run_benchmarks", "make_synthetic_hits"]


@dataclass(slots=True)
class BenchResult:
    """One benchmark measurement."""

    name: str
    seconds: float
    extra: str


def make_synthetic_hits(
    count: int,
    *,
    seed: int = 7,
    duplicate_rate: float = 0.4,
) -> list[dict[str, Any]]:
    """Build ``count`` fake search hits with scores and planted duplicates."""
    rng = random.Random(seed)
    topics = [
        "rtx 5090 preco oferta brasil",
        "ryzen 7 9800x3d disponivel estoque",
        "ddr5 32gb kit barato promocao",
        "placa mae b650 am5 review",
    ]
    hits: list[dict[str, Any]] = []
    for index in range(count):
        topic = rng.choice(topics)
        if rng.random() < duplicate_rate and hits:
            # Planted near-duplicate: same snippet, new URL, lower score.
            source = rng.choice(hits)
            hits.append(
                {
                    "url": f"https://shop{index}.example/item",
                    "title": source["title"],
                    "snippet": source["snippet"],
                    "score": source["score"] * 0.5,
                }
            )
            continue
        snippet = (
            f"{topic} por R$ {rng.randrange(500, 20000)},00 em ate 12x "
            f"com frete gratis para todo o brasil oferta valida hoje {index}"
        )
        hits.append(
            {
                "url": f"https://shop{index}.example/item",
                "title": topic,
                "snippet": snippet,
                "score": round(rng.random(), 3),
            }
        )
    return hits


def bench_pack_hits(count: int = 400) -> BenchResult:
    """Time packing ``count`` synthetic hits into a fixed token budget."""
    hits = make_synthetic_hits(count)
    start = time.perf_counter()
    result = pack_hits(hits, budget_tokens=4000)
    elapsed = time.perf_counter() - start
    return BenchResult(
        name="pack_hits",
        seconds=elapsed,
        extra=savings_report(result, len(hits)),
    )


def bench_dedupe_quality(count: int = 400) -> BenchResult:
    """Measure how many planted duplicates the packer removes."""
    hits = make_synthetic_hits(count, duplicate_rate=0.4)
    result = pack_hits(hits, budget_tokens=1_000_000)
    planted = int(count * 0.4)
    caught = result.duplicates_dropped
    recall = caught / planted if planted else 1.0
    return BenchResult(
        name="dedupe_quality",
        seconds=0.0,
        extra=f"caught {caught}/{planted} planted duplicates (recall {recall:.0%})",
    )


def bench_estimate_tokens(count: int = 50_000) -> BenchResult:
    """Time the token estimator over ``count`` short strings."""
    texts = [f"sample text number {i} with some words" for i in range(count)]
    start = time.perf_counter()
    total = sum(estimate_tokens(text) for text in texts)
    elapsed = time.perf_counter() - start
    return BenchResult(
        name="estimate_tokens",
        seconds=elapsed,
        extra=f"{count / elapsed:,.0f} strings/sec, {total} tokens estimated",
    )


def run_benchmarks() -> list[BenchResult]:
    """Run every benchmark and print one line each."""
    results = [bench_pack_hits(), bench_dedupe_quality(), bench_estimate_tokens()]
    for result in results:
        print(f"{result.name:16s} {result.seconds * 1000:8.1f} ms  {result.extra}")
    return results


if __name__ == "__main__":
    run_benchmarks()
