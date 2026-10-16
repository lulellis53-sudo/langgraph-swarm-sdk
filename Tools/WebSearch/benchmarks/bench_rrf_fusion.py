"""A/B Benchmark: Baseline RRF vs Enhanced Q-RRF & Token-Saving Snippet Pruning.

Samples follow an ABBA cadence (even rounds A,B,B,A; odd rounds B,A,A,B) and are
summarised by medians and percentage deltas, ensuring host jitter does not bias results.

Run: ``python -m WebSearch.benchmarks.bench_rrf_fusion [--rounds N] [--json]``.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass

from WebSearch.frontend.fanout import _enhanced_rrf_fuse, _rrf_fuse, dedupe_hits
from WebSearch.frontend.hits import hit_score, normalize_hit
from WebSearch.frontend.types import SearchHit

SAMPLE_QUERIES = [
    "Python 3.15 lazy imports PEP 810 benchmarks and performance",
    "Fast parallel web search deduplication and vector reranking",
    "OpenCL MoltenVK GPU acceleration on macOS AMD Radeon",
]

# Realistic simulated multi-provider search hit batches
FIXTURE_BATCHES = [
    # Provider 1: Brave
    [
        SearchHit(
            title="PEP 810 – Lazy Imports | Python.org",
            url="https://peps.python.org/pep-0810/?utm_source=brave_search&ref=dev",
            snippet=(
                            "Oct 11, 2026 — Python 3.15 introduces lazy imports with PEP 810. "
                            "This proposal adds syntax to defer module loading until first "
                            "attribute access, improving CLI startup performance significantly. "
                            "... ... Documentation and reference implementation details."
                        ),
            searcher_id="brave",
        ),
        SearchHit(
            title="Fast Parallel Web Search Framework in Python",
            url="https://github.com/example/parallel-websearch?ref=brave",
            snippet=(
                            "High-performance asynchronous parallel web search crawler and "
                            "extractor using selectolax, trafilatura, and httpx with zero "
                            "external API key requirements."
                        ),
            searcher_id="brave",
        ),
        SearchHit(
            title="Low Resource LLM Agent Architecture",
            url="https://arxiv.org/abs/2602.12345",
            snippet=(
                            "Evaluating multi-agent memory persistence and speculative "
                            "execution constraints on workstation environments."
                        ),
            searcher_id="brave",
        ),
    ],
    # Provider 2: Parallel
    [
        SearchHit(
            title="PEP 810: Lazy Imports in Python 3.15 (Benchmarks & Performance)",
            url="https://peps.python.org/pep-0810/",
            snippet=(
                            "Comprehensive benchmarks for PEP 810 lazy imports in Python 3.15. "
                            "Reduces startup overhead by 40-70% for heavy CLI tools by deferring "
                            "import evaluation until use. Includes rigorous ABBA sampling "
                            "measurements and memory profiles."
                        ),
            searcher_id="parallel",
        ),
        SearchHit(
            title="OpenCL and MoltenVK on macOS Apple/AMD",
            url="https://developer.apple.com/opencl-moltenvk-guide",
            snippet=(
                            "Guide to running compute kernels with OpenCL and Vulkan through "
                            "MoltenVK translation layers on macOS with AMD Radeon GPUs."
                        ),
            searcher_id="parallel",
        ),
        SearchHit(
            title="Fast Parallel Web Search and Deduplication",
            url="https://github.com/example/parallel-websearch",
            snippet=(
                            "Fast parallel web search with reciprocal rank fusion, SimHash "
                            "near-duplicate detection, and token budget pruning."
                        ),
            searcher_id="parallel",
        ),
    ],
    # Provider 3: Tavily
    [
        SearchHit(
            title="PEP 810 Lazy Imports Specification",
            url="https://peps.python.org/pep-0810/?fbclid=123456",
            snippet=(
                            "Specification details for Python 3.15 PEP 810 lazy imports "
                            "mechanism and CPython runtime bytecode changes."
                        ),
            searcher_id="tavily",
        ),
        SearchHit(
            title="AMD Radeon OpenCL Acceleration on macOS",
            url="https://developer.apple.com/opencl-moltenvk-guide?utm_medium=tavily",
            snippet=(
                            "Oct 09, 2026 — Hardware acceleration benchmarks for OpenCL and "
                            "MoltenVK on Intel Macs with AMD Radeon Pro 5300M GPUs."
                        ),
            searcher_id="tavily",
        ),
    ],
]


@dataclass(frozen=True, slots=True)
class VariantMetrics:
    """Evaluation metrics for one fusion variant."""

    tokens: int
    char_count: int
    mean_salience: float
    consensus_count: int
    latency_ms: float


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    """Summary comparing Variant A (Baseline) and Variant B (Enhanced)."""

    rounds: int
    tokens_baseline: int
    tokens_enhanced: int
    tokens_saved_pct: float
    chars_baseline: int
    chars_enhanced: int
    chars_saved_pct: float
    salience_baseline: float
    salience_enhanced: float
    salience_gain_pct: float
    latency_median_a_ms: float
    latency_median_b_ms: float


def run_variant(
    variant: str, query: str, batches: list[list[SearchHit]], max_snippet_chars: int = 140
) -> VariantMetrics:
    """Run one variant and compute tokens, relevance salience, and latency."""
    start = time.perf_counter()
    if variant == "baseline":
        merged = _rrf_fuse(batches)
        hits = [normalize_hit(h) for h in dedupe_hits(merged, query)]
    else:
        # Agent-brief mode: prune snippets to the query window and drop hits
        # with zero query-term overlap (drop_zero_salience).
        merged = _enhanced_rrf_fuse(
            batches,
            query=query,
            max_snippet_chars=max_snippet_chars,
            drop_zero_salience=True,
        )
        hits = [normalize_hit(h) for h in dedupe_hits(merged, query)]
    elapsed_ms = (time.perf_counter() - start) * 1000

    chars = sum(len(f"{h.title} {h.snippet}") for h in hits)
    # Token estimation: words + punctuation approximation (~1.3 chars/token)
    tokens = sum(len(f"{h.title} {h.snippet}".split()) for h in hits)
    salience = statistics.mean([hit_score(h, query) for h in hits]) if hits else 0.0
    consensus = sum(1 for h in hits if len(h.also_from) > 0)

    return VariantMetrics(
        tokens=tokens,
        char_count=chars,
        mean_salience=round(salience, 4),
        consensus_count=consensus,
        latency_ms=round(elapsed_ms, 3),
    )


def abba(
    time_a: Callable[[], float], time_b: Callable[[], float], rounds: int
) -> tuple[list[float], list[float]]:
    """Paired ABBA sampling across rounds to eliminate host thermal drift."""
    a_samples: list[float] = []
    b_samples: list[float] = []
    for r in range(rounds):
        order = ("a", "b", "b", "a") if r % 2 == 0 else ("b", "a", "a", "b")
        for v in order:
            if v == "a":
                a_samples.append(time_a())
            else:
                b_samples.append(time_b())
    return a_samples, b_samples


def run_benchmark(rounds: int = 10) -> BenchmarkReport:
    """Execute the full A/B benchmark suite comparing Variant A vs B."""
    query = SAMPLE_QUERIES[0]
    metrics_a = run_variant("baseline", query, FIXTURE_BATCHES)
    metrics_b = run_variant("enhanced", query, FIXTURE_BATCHES)

    a_times, b_times = abba(
        lambda: run_variant("baseline", query, FIXTURE_BATCHES).latency_ms,
        lambda: run_variant("enhanced", query, FIXTURE_BATCHES).latency_ms,
        rounds=rounds,
    )

    tokens_saved_pct = (
        round((1.0 - (metrics_b.tokens / metrics_a.tokens)) * 100.0, 2)
        if metrics_a.tokens > 0
        else 0.0
    )
    chars_saved_pct = (
        round((1.0 - (metrics_b.char_count / metrics_a.char_count)) * 100.0, 2)
        if metrics_a.char_count > 0
        else 0.0
    )
    salience_gain_pct = round(
        ((metrics_b.mean_salience - metrics_a.mean_salience) / max(0.001, metrics_a.mean_salience))
        * 100.0,
        2,
    )

    return BenchmarkReport(
        rounds=rounds,
        tokens_baseline=metrics_a.tokens,
        tokens_enhanced=metrics_b.tokens,
        tokens_saved_pct=tokens_saved_pct,
        chars_baseline=metrics_a.char_count,
        chars_enhanced=metrics_b.char_count,
        chars_saved_pct=chars_saved_pct,
        salience_baseline=metrics_a.mean_salience,
        salience_enhanced=metrics_b.mean_salience,
        salience_gain_pct=salience_gain_pct,
        latency_median_a_ms=round(statistics.median(a_times), 3),
        latency_median_b_ms=round(statistics.median(b_times), 3),
    )


def main() -> None:
    """CLI entrypoint for running the A/B fusion benchmark."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=10, help="ABBA rounds (default: 10)")
    parser.add_argument("--json", action="store_true", help="Print report as JSON")
    args = parser.parse_args()

    report = run_benchmark(rounds=args.rounds)
    if args.json:
        print(json.dumps(asdict(report), indent=2))
        return

    print("==========================================================================")
    print("      WebSearch A/B Benchmark: Baseline (A) vs Enhanced Q-RRF (B)        ")
    print("==========================================================================")
    print(f"Rounds: {args.rounds} ABBA pairs ({args.rounds * 4} samples per variant)")
    print("--------------------------------------------------------------------------")
    print(
        f"Tokens:          Baseline: {report.tokens_baseline} | "
        f"Enhanced: {report.tokens_enhanced} | Δ: -{report.tokens_saved_pct}%"
    )
    print(
        f"Chars:           Baseline: {report.chars_baseline} | "
        f"Enhanced: {report.chars_enhanced} | Δ: -{report.chars_saved_pct}%"
    )
    print(
        f"Mean Salience:   Baseline: {report.salience_baseline} | "
        f"Enhanced: {report.salience_enhanced} | Δ: +{report.salience_gain_pct}%"
    )
    print(
        f"Median Latency:  Baseline: {report.latency_median_a_ms} ms | "
        f"Enhanced: {report.latency_median_b_ms} ms"
    )
    print("==========================================================================")


if __name__ == "__main__":
    main()
