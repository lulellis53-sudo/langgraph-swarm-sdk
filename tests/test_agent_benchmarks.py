"""Benchmark regression test suite guarding against latency, cost, and JEV regressions."""

from swarm_sdk.models.selection import select_model_tier
from swarm_sdk.observability.telemetry import collect_agent_telemetry, summarize_telemetry
from swarm_sdk.prompting.pruner import compress_prompt_bloat


def test_telemetry_aggregation_benchmark(benchmark):
    """Benchmark telemetry aggregation performance across all agent logs."""
    summary = benchmark(summarize_telemetry, collect_agent_telemetry())
    assert "total_agents" in summary
    assert summary["total_agents"] >= 0


def test_prompt_compression_benchmark(benchmark):
    """Benchmark TokenSaver prompt compression latency and token reduction."""
    bloated_prompt = "# Comment Line\n" + ("System directive info sentence.\n" * 200)
    compressed = benchmark(
        compress_prompt_bloat, bloated_prompt, max_token_threshold=100, target_max_tokens=50
    )
    assert len(compressed) < len(bloated_prompt)


def test_model_tier_selection_benchmark(benchmark):
    """Benchmark dynamic model tiering decision latency."""
    model, think_level = benchmark(select_model_tier, "low")
    assert model == "google_genai:gemini-2.5-flash"
    assert think_level == "low"


def test_rrf_score_fusion_benchmark(benchmark):
    """Benchmark Reciprocal Rank Fusion (RRF) score calculation latency."""
    from swarm_sdk.retrieval.hybrid import rrf_merge_scores

    rankings = [list(range(100)), list(reversed(range(100)))]
    scores = benchmark(rrf_merge_scores, rankings, k=60)
    assert len(scores) == 100


def test_zero_copy_tokenize_benchmark(benchmark):
    """Benchmark zero-copy memoryview tokenization latency vs text size."""
    from swarm_sdk.retrieval.text import tokenize_zero_copy

    sample_text = (
        "The quick brown fox jumps over 13 lazy dogs in an agentic memory swarm loop. " * 50
    )
    tokens = benchmark(tokenize_zero_copy, sample_text)
    assert len(tokens) > 0
