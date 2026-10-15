"""Offline tests for Newsletter digest builder."""

from __future__ import annotations

import pytest
from Newsletter import SourceSnippet, build_digest


def test_build_digest_dedupes_identical_bodies() -> None:
    sources = [
        SourceSnippet("One", "Same text."),
        SourceSnippet("Two", "Same text."),
        SourceSnippet("Three", "Different."),
    ]
    result = build_digest("Test", sources)
    assert result.source_count == 2
    assert "Different." in result.markdown
    assert result.word_count > 0


def test_build_digest_includes_url() -> None:
    result = build_digest(
        "Links",
        [SourceSnippet("A", "Body", url="https://example.com/x")],
    )
    assert "https://example.com/x" in result.markdown


def test_build_digest_rejects_empty_title() -> None:
    with pytest.raises(ValueError, match="title"):
        build_digest("", [SourceSnippet("A", "x")])
