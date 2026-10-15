"""Tests for the LangExtract backend wrapper (offline, no LLM calls)."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest
from WebSearch.Core.backend.langextract_doc import (
    extract_fields,
    grounded_extractions_to_dicts,
)


def _interval(start: int, end: int) -> SimpleNamespace:
    """Duck-typed char_interval."""
    return SimpleNamespace(start_pos=start, end_pos=end)


_SOURCE = "Lady Juliet gazed longingly at the stars, her heart aching for Romeo"


def test_converter_slices_grounded_quote_from_source() -> None:
    """A grounded extraction carries the verbatim quote from the source text."""
    extraction = SimpleNamespace(
        extraction_class="character",
        extraction_text="Juliet",
        attributes={"identity": "Capulet daughter"},
        char_interval=_interval(5, 11),
        extractions=(),
    )
    rows = grounded_extractions_to_dicts([extraction], source_text=_SOURCE)
    assert rows[0]["grounded"] is True
    assert rows[0]["quote"] == "Juliet"
    assert rows[0]["start_pos"] == 5
    assert rows[0]["attributes"] == {"identity": "Capulet daughter"}


def test_converter_marks_ungrounded_span() -> None:
    """char_interval=None (hallucinated span) becomes grounded=false, quote=None."""
    extraction = SimpleNamespace(
        extraction_class="emotion",
        extraction_text="longing",
        attributes={},
        char_interval=None,
        extractions=(),
    )
    rows = grounded_extractions_to_dicts([extraction], source_text=_SOURCE)
    assert rows[0]["grounded"] is False
    assert rows[0]["quote"] is None


def test_converter_flattens_nested_extractions() -> None:
    """Nested extractions appear under a child ``extractions`` list."""
    child = SimpleNamespace(
        extraction_class="name",
        extraction_text="Romeo",
        attributes={},
        char_interval=_interval(56, 61),
        extractions=(),
    )
    parent = SimpleNamespace(
        extraction_class="character",
        extraction_text="Romeo",
        attributes={},
        char_interval=_interval(56, 61),
        extractions=(child,),
    )
    rows = grounded_extractions_to_dicts([parent], source_text=_SOURCE)
    assert rows[0]["extractions"][0]["text"] == "Romeo"


def test_extract_fields_empty_text_returns_without_import() -> None:
    """Empty source short-circuits before importing the heavy dependency."""
    assert extract_fields("   ", "extract names") == []


def test_extract_fields_fails_closed_without_package(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing langextract install raises OSError with the sync hint."""
    monkeypatch.setitem(sys.modules, "langextract", None)
    with pytest.raises(OSError, match="uv sync --extra langextract"):
        extract_fields(_SOURCE, "extract characters")


def test_extract_fields_live_grounding() -> None:
    """Live smoke against Gemini; skipped without langextract + GEMINI_API_KEY."""
    import importlib.util
    import os

    if importlib.util.find_spec("langextract") is None or not os.environ.get("GEMINI_API_KEY"):
        pytest.skip("langextract extra or GEMINI_API_KEY not available")
    rows = extract_fields(
        _SOURCE,
        "Extract named characters and their emotions as attributes.",
        max_char_buffer=500,
    )
    assert rows, "live langextract returned no extractions"
    assert any(row["class"] for row in rows)
