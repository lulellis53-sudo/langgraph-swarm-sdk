"""Backend: HTML extractors, text normalization and document dedupe.

Order from ``providers.yaml``: selectolax, selectolax_regex, regex,
trafilatura, bs4. Missing optional libs skip to the next extractor.
"""

from __future__ import annotations

from WebSearch.backend.docs import (
    ExtractedDoc,
    dedupe_docs,
    extract_and_normalize,
    type_is_extracted,
)
from WebSearch.backend.normalize import normalize_text
from WebSearch.backend.prefilter import (
    Rejected,
    RejectReason,
    prefilter_hits,
    unwrap_redirect,
)

__all__ = [
    "ExtractedDoc",
    "RejectReason",
    "Rejected",
    "dedupe_docs",
    "extract_and_normalize",
    "normalize_text",
    "prefilter_hits",
    "type_is_extracted",
    "unwrap_redirect",
]
