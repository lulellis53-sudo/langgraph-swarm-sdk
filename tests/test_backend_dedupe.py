"""Tests for URL/text normalization and the three dedupe layers in backend/docs.py."""

from __future__ import annotations

import pytest
from WebSearch.backend.docs import ExtractedDoc, dedupe_docs
from WebSearch.backend.normalize import normalize_text, normalize_url


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (
            "https://Example.com/docs/Page?a=1&utm_source=x&utm_campaign=y",
            "https://example.com/docs/Page?a=1",
        ),
        ("https://example.com/page#section", "https://example.com/page"),
        ("https://example.com:443/a", "https://example.com/a"),
        ("http://example.com:80/a", "http://example.com/a"),
        ("https://example.com:8443/a", "https://example.com:8443/a"),
        ("https://example.com/a/", "https://example.com/a"),
        ("https://example.com/b?z=1&a=2", "https://example.com/b?a=2&z=1"),
        (
            "https://example.com/x?gclid=abc&id=7",
            "https://example.com/x?id=7",
        ),
        (
            "https://example.com/x?fbclid=abc&ref_src=rss&id=7",
            "https://example.com/x?id=7",
        ),
    ],
)
def test_normalize_url_collapses_provider_variants(left: str, right: str) -> None:
    assert normalize_url(left) == normalize_url(right)


def test_normalize_url_keeps_meaningful_query_and_blank_query() -> None:
    assert normalize_url("https://example.com/search?q=python") == (
        "https://example.com/search?q=python"
    )
    assert normalize_url("https://example.com/a?") == "https://example.com/a"


def test_normalize_url_leaves_relative_and_schemeless_alone() -> None:
    for raw in ("/docs/page", "//example.com/a", "not a url"):
        assert normalize_url(raw) == raw


def test_normalize_text_still_canonicalizes_lines() -> None:
    noisy = "Title\n\u00a0\u2014 \u2014 \u2014\nTitle\nBody text here\n"
    assert normalize_text(noisy) == "Title Body text here"


def test_dedupe_docs_drops_same_canonical_url_with_different_text() -> None:
    first = ExtractedDoc(
        url="https://example.com/post?utm_source=news",
        text="alpha body",
        extractor="t",
        raw_chars=10,
    )
    second = ExtractedDoc(
        url="https://example.com/post?utm_source=feed",
        text="totally different",
        extractor="t",
        raw_chars=17,
    )
    assert dedupe_docs([first, second]) == [first]


def test_dedupe_docs_keeps_distinct_urls_with_similar_short_text() -> None:
    first = ExtractedDoc(
        url="https://a.example/x", text="alpha report", extractor="t", raw_chars=12
    )
    second = ExtractedDoc(
        url="https://b.example/x", text="alpha notes", extractor="t", raw_chars=11
    )
    assert dedupe_docs([first, second]) == [first, second]


def test_dedupe_docs_still_drops_empty_exact_and_near_duplicates() -> None:
    empty = ExtractedDoc(url="https://a.example/1", text="", extractor="t", raw_chars=1)
    exact = ExtractedDoc(url="https://a.example/2", text="same words", extractor="t", raw_chars=10)
    exact_copy = ExtractedDoc(
        url="https://b.example/2", text="Same Words", extractor="t", raw_chars=10
    )
    keep = ExtractedDoc(
        url="https://a.example/3", text="unrelated body", extractor="t", raw_chars=14
    )
    result = dedupe_docs([empty, exact, exact_copy, keep])
    assert [doc.url for doc in result] == ["https://a.example/2", "https://a.example/3"]


def test_normalize_url_preserves_ipv6_host_brackets() -> None:
    assert normalize_url("HTTPS://[2001:DB8::1]:443/a#top") == "https://[2001:db8::1]/a"


def test_dedupe_docs_can_stream_a_generator() -> None:
    docs = (
        ExtractedDoc(f"https://example.com/{i}", f"different content {i}", "x", 10)
        for i in range(2)
    )
    assert len(dedupe_docs(docs)) == 2
