"""Extraction pipeline and document-level dedupe."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from WebSearch.backend.extractors import extract_text, strip_tags
from WebSearch.backend.normalize import normalize_text
from WebSearch.frontend.providers import ExtractorName, ProvidersConfig, load_providers

ExtractorUsed = ExtractorName | Literal["fallback"]


@dataclass(frozen=True, slots=True)
class ExtractedDoc:
    text: str
    extractor: ExtractorUsed
    url: str = ""
    raw_chars: int = 0

    @property
    def reduction(self) -> float:
        """Fraction of the source HTML removed by extraction + normalization (0..1)."""
        if self.raw_chars <= 0:
            return 0.0
        return max(0.0, 1.0 - len(self.text) / self.raw_chars)


def dedupe_docs(docs: Iterable[ExtractedDoc]) -> list[ExtractedDoc]:
    """Drop empty docs and docs whose normalized text duplicates an earlier one.

    Catches mirrors and the same page served under different URLs.

    Args:
        docs (Iterable[ExtractedDoc]): Docs in priority order.

    Returns:
        list[ExtractedDoc]: Unique non-empty docs, order preserved.
    """
    seen: set[str] = set()
    unique: list[ExtractedDoc] = []
    for doc in docs:
        if not doc.text:
            continue
        digest = hashlib.blake2b(doc.text.casefold().encode(), digest_size=16).hexdigest()
        if digest not in seen:
            seen.add(digest)
            unique.append(doc)
    return unique


def type_is_extracted(value: object) -> bool:
    """Return whether *value* is an ``ExtractedDoc``.

    Args:
        value (object): Candidate object.

    Returns:
        bool: True if ``ExtractedDoc``.
    """
    return isinstance(value, ExtractedDoc)


def extract_and_normalize(
    html: str,
    *,
    url: str = "",
    config: ProvidersConfig | None = None,
) -> ExtractedDoc:
    """Try extractors in yaml order; always run ``normalize_text`` on the winner.

    Args:
        html (str): Page HTML.
        url (str): Source URL stored on the doc.
        config (ProvidersConfig | None): Extractor order.

    Returns:
        ExtractedDoc: Normalized text and which extractor produced it.
    """
    order = (config or load_providers()).extractor_order
    last_text = ""
    used: ExtractorUsed = "fallback"
    for name in order:
        text = extract_text(name, html)
        if text:
            last_text = text
            used = name
            break
    if not last_text:
        last_text = strip_tags(html)
        used = "fallback"
    return ExtractedDoc(
        text=normalize_text(last_text), extractor=used, url=url, raw_chars=len(html)
    )


__all__ = ["ExtractedDoc", "dedupe_docs", "extract_and_normalize", "type_is_extracted"]
