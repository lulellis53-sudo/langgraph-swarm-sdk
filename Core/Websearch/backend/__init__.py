"""Backend document extraction, normalization, and deduplication."""

from __future__ import annotations

lazy from WebSearch.Core.backend.docs import (
    ExtractedDoc,
    dedupe_docs,
    extract_and_normalize,
    type_is_extracted,
)
lazy from WebSearch.Core.backend.normalize import normalize_text

__all__ = [
    "ExtractedDoc",
    "dedupe_docs",
    "extract_and_normalize",
    "normalize_text",
    "type_is_extracted",
]
