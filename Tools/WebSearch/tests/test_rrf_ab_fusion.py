"""Test suite for WebSearch 2026 stack: Q-RRF fusion, dedupers, normalizators, and token savings."""

from __future__ import annotations

from WebSearch.benchmarks.bench_rrf_fusion import FIXTURE_BATCHES, run_variant
from WebSearch.backend.docs import compute_minhash
from WebSearch.backend.extractors import extract_text
from WebSearch.backend.normalize import clean_snippet_noise, normalize_text
from WebSearch.backend.prefilter import (
    PrefilterPolicy,
    RejectReason,
    clean_tracking_url,
    prefilter_hits,
)
from WebSearch.frontend.fanout import _enhanced_rrf_fuse
from WebSearch.frontend.hits import (
    is_fuzzy_duplicate_title,
    prune_snippet_to_query,
)
from WebSearch.frontend.types import SearchHit


# 1. URL tracking parameter cleaning
def test_clean_tracking_url_strips_marketing_params() -> None:
    raw = "https://example.com/page?utm_source=twitter&utm_medium=cpc&gclid=xyz123&keep=1"
    cleaned = clean_tracking_url(raw)
    assert "utm_source" not in cleaned
    assert "gclid" not in cleaned
    assert "keep=1" in cleaned


# 2. Junk snippet prefiltering
def test_prefilter_rejects_junk_error_snippets() -> None:
    policy = PrefilterPolicy(reject_junk=True, min_snippet_chars=5)
    junk_hits = [
        SearchHit(
            "Page 1",
            "https://a.example/1",
            "404 Not Found - The requested URL was not found on this server.",
            "brave",
        ),
        SearchHit(
            "Page 2",
            "https://a.example/2",
            "Access Denied: You do not have permission to access this resource.",
            "brave",
        ),
        SearchHit(
            "Page 3",
            "https://a.example/3",
            "Please verify you are human to continue. Cloudflare Ray ID: 890123",
            "brave",
        ),
        SearchHit(
            "Valid Page",
            "https://a.example/4",
            "Python 3.15 includes official support for PEP 810 lazy imports syntax.",
            "brave",
        ),
    ]
    kept, rejected = prefilter_hits(junk_hits, policy)
    assert len(kept) == 1
    assert kept[0].title == "Valid Page"
    assert len(rejected) == 3
    assert all(r.reason == RejectReason.junk_snippet for r in rejected)


# 3. Snippet length clamping at prefilter
def test_prefilter_clamps_excessive_snippet_length() -> None:
    policy = PrefilterPolicy(max_snippet_chars=50, min_snippet_chars=5)
    long_hit = SearchHit("Title", "https://a.example", "A" * 100, "brave")
    kept, _ = prefilter_hits([long_hit], policy)
    assert len(kept) == 1
    assert len(kept[0].snippet) <= 53  # 50 chars + "..."


# 4. Text noise & timestamp cleaning
def test_clean_snippet_noise_removes_dates_and_ellipsis() -> None:
    noisy = (
        "Oct 11, 2026 — Breaking news: Python 3.15 released ... ... "
        "with new features --- details inside."
    )
    cleaned = clean_snippet_noise(noisy)
    assert "Oct 11, 2026" not in cleaned
    assert "... ..." not in cleaned
    assert "Breaking news: Python 3.15 released" in cleaned


# 5. Mojibake repair via ftfy
def test_normalize_text_repairs_mojibake() -> None:
    mojibake = "Itâ€™s an awesome Python 3.15 release &amp; feature!"
    cleaned = normalize_text(mojibake)
    assert "It's an awesome Python 3.15 release & feature!" in cleaned


# 6. RapidFuzz title near-duplicate detection
def test_is_fuzzy_duplicate_title_detects_near_identical_titles() -> None:
    t1 = "PEP 810 – Lazy Imports | Python.org"
    t2 = "PEP 810: Lazy Imports in Python"
    t3 = "Completely Unrelated Machine Learning Paper"
    assert is_fuzzy_duplicate_title(t1, t2, threshold=75.0) is True
    assert is_fuzzy_duplicate_title(t1, t3, threshold=75.0) is False


# 7. Query-salient snippet pruning
def test_prune_snippet_to_query_preserves_query_sentences() -> None:
    snippet = (
        "Welcome to the homepage. Cookie policy applies. "
        "Python 3.15 introduces PEP 810 lazy imports for faster startup. "
        "Contact support at support@example.com for advertising."
    )
    query = "Python 3.15 lazy imports"
    pruned = prune_snippet_to_query(snippet, query, max_chars=80)
    assert "Python 3.15 introduces PEP 810 lazy imports" in pruned
    assert "Cookie policy" not in pruned
    assert len(pruned) <= 80


def test_prune_snippet_drops_filler_under_char_budget() -> None:
    snippet = (
        "Welcome to the homepage and cookie policy. "
        "Python 3.15 introduces PEP 810 lazy imports for faster startup. "
        "Contact support at support@example.com for advertising."
    )
    query = "Python 3.15 lazy imports PEP 810 benchmarks and performance"
    pruned = prune_snippet_to_query(snippet, query, max_chars=400)
    assert "Python 3.15 introduces PEP 810 lazy imports" in pruned
    assert "cookie policy" not in pruned.casefold()
    assert "Contact support" not in pruned


# 8. Consensus copy selection and also_from accumulation in Q-RRF
def test_enhanced_rrf_picks_best_copy_and_accumulates_provenance() -> None:
    batch1 = [
        SearchHit("Short Title", "https://python.org/pep", "Short snippet", "brave"),
    ]
    batch2 = [
        SearchHit(
            "PEP 810: Lazy Imports in Python 3.15",
            "https://python.org/pep",
            "Rich and informative snippet explaining PEP 810 lazy imports in Python 3.15.",
            "parallel",
        ),
    ]
    query = "PEP 810 lazy imports Python 3.15"
    fused = _enhanced_rrf_fuse([batch1, batch2], query=query)
    assert len(fused) == 1
    best = fused[0]
    # Kept the richer copy
    assert "PEP 810: Lazy Imports" in best.title
    # Accumulated provenance
    assert "brave" in best.also_from or best.searcher_id == "brave"
    assert "parallel" in best.also_from or best.searcher_id == "parallel"


# 9. Extractors: inscriptis and markdownify
def test_inscriptis_and_markdownify_extractors() -> None:
    html = "<html><body><h1>Title</h1><p>Paragraph with <b>bold text</b> and <a href='https://example.com'>link</a>.</p></body></html>"
    text_inscriptis = extract_text("inscriptis", html)
    assert "Title" in text_inscriptis
    assert "Paragraph with bold text" in text_inscriptis

    text_md = extract_text("markdownify", html)
    assert "# Title" in text_md or "Title" in text_md
    assert "bold text" in text_md


# 10. MinHash computation
def test_compute_minhash_produces_valid_signature() -> None:
    doc1 = "Python 3.15 PEP 810 lazy imports fast parallel web search deduplication"
    doc2 = "Python 3.15 PEP 810 lazy imports fast parallel web search deduplication"
    doc3 = "Completely different text about Vulkan GPU compute shaders and shaders"
    mh1 = compute_minhash(doc1)
    mh2 = compute_minhash(doc2)
    mh3 = compute_minhash(doc3)
    assert mh1 is not None and mh2 is not None and mh3 is not None
    assert mh1.jaccard(mh2) == 1.0
    assert mh1.jaccard(mh3) < 0.2


# 11. Quantified token reduction benchmark validation
def test_token_reduction_on_benchmark_fixtures() -> None:
    query = "Python 3.15 lazy imports PEP 810 benchmarks and performance"
    metrics_a = run_variant("baseline", query, FIXTURE_BATCHES)
    metrics_b = run_variant("enhanced", query, FIXTURE_BATCHES)

    # Enhanced variant must save at least 20% tokens and chars
    token_saving_pct = (1.0 - (metrics_b.tokens / metrics_a.tokens)) * 100.0
    char_saving_pct = (1.0 - (metrics_b.char_count / metrics_a.char_count)) * 100.0

    assert token_saving_pct >= 20.0, f"Expected >= 20% token savings, got {token_saving_pct:.2f}%"
    assert char_saving_pct >= 20.0, f"Expected >= 20% char savings, got {char_saving_pct:.2f}%"
    # Enhanced salience must be >= baseline
    assert metrics_b.mean_salience >= metrics_a.mean_salience
