"""Extraction pipeline and document-level dedupe."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass

import regex as re

from WebSearch.backend.extractors import extract_text, strip_tags
from WebSearch.backend.normalize import normalize_text, normalize_url
from WebSearch.frontend.websearchers import ProvidersConfig, load_providers

_TOKEN = re.compile(r"\w+")
_SHINGLE = 5
_BITS = 64
#: Hamming distance at which two docs count as mirrors of the same page.
_NEAR_MAX_DISTANCE = 12
_SIMHASH_BANDS = 13


@dataclass(frozen=True, slots=True)
class ExtractedDoc:
    """Normalized page text produced by the extractor pipeline."""

    url: str
    text: str
    extractor: str
    raw_chars: int

    @property
    def reduction(self) -> float:
        """Fraction of the source HTML removed by extraction + normalization (0..1)."""
        if self.raw_chars <= 0:
            return 0.0
        return max(0.0, 1.0 - (len(self.text) / self.raw_chars))


def _simhash(text: str) -> int | None:
    """64-bit SimHash over word 5-shingles; ``None`` when the text is too short."""
    tokens = _TOKEN.findall(text.casefold())
    if len(tokens) < _SHINGLE:
        return None
    votes = [0] * _BITS
    for start in range(len(tokens) - _SHINGLE + 1):
        digest = hashlib.blake2b(
            " ".join(tokens[start : start + _SHINGLE]).encode(), digest_size=_BITS // 8
        ).digest()
        value = int.from_bytes(digest, "big")
        for bit in range(_BITS):
            votes[bit] += 1 if (value >> bit) & 1 else -1
    return sum(1 << bit for bit, vote in enumerate(votes) if vote > 0)


def _simhash_bands(fingerprint: int) -> tuple[tuple[int, int], ...]:
    """Return 13 locality-sensitive keys; any pair within distance 12 shares one."""
    bands: list[tuple[int, int]] = []
    offset = 0
    for band in range(_SIMHASH_BANDS):
        width = min(5, _BITS - offset)
        bands.append((band, (fingerprint >> offset) & ((1 << width) - 1)))
        offset += width
    return tuple(bands)


def dedupe_docs(docs: Iterable[ExtractedDoc]) -> list[ExtractedDoc]:
    """Drop empty docs and docs duplicating an earlier one, by URL, exact, or near.

    Canonical URLs (tracking parameters stripped, host case-folded) collapse the
    same page reached through provider-specific links. Exact duplicates share the
    casefolded-text hash; near-duplicates (mirrors, the same page under different
    URLs, boilerplate-shuffled copies) are caught by Hamming distance between
    64-bit SimHashes of word shingles.

    Args:
        docs (Iterable[ExtractedDoc]): Docs in priority order.

    Returns:
        list[ExtractedDoc]: Unique non-empty docs, order preserved.
    """
    seen_urls: set[str] = set()
    seen: set[str] = set()
    fingerprints: list[int] = []
    band_index: dict[tuple[int, int], list[int]] = {}
    unique: list[ExtractedDoc] = []
    for doc in docs:
        if not doc.text:
            continue
        canonical = normalize_url(doc.url)
        if canonical in seen_urls:
            continue
        seen_urls.add(canonical)
        h = hashlib.blake2b(doc.text.casefold().encode("utf-8"), digest_size=16).hexdigest()
        if h in seen:
            continue
        fingerprint = _simhash(doc.text)
        if fingerprint is not None:
            candidates: set[int] = set()
            for band in _simhash_bands(fingerprint):
                candidates.update(band_index.get(band, ()))
            if any(
                (fingerprint ^ fingerprints[index]).bit_count() <= _NEAR_MAX_DISTANCE
                for index in candidates
            ):
                continue
            index = len(fingerprints)
            fingerprints.append(fingerprint)
            for band in _simhash_bands(fingerprint):
                band_index.setdefault(band, []).append(index)
        seen_urls.add(canonical)
        seen.add(h)
        unique.append(doc)
    return unique


def type_is_extracted(value: object) -> bool:
    """Return whether *value* is an ExtractedDoc."""
    return isinstance(value, ExtractedDoc)


def extract_and_normalize(
    html: str,
    url: str,
    config: ProvidersConfig | None = None,
    *,
    main_first: bool = False,
) -> ExtractedDoc:
    """Try extractors in yaml order; always run normalize_text on the winner.

    Args:
        html: Page HTML.
        url: Page URL, kept on the result.
        config: Providers config; default ``load_providers()``.
        main_first: Try ``trafilatura`` (main article text, no menus or footers) before
            the configured order. Falls through when it is missing or finds nothing.
    """
    order = (config or load_providers()).extractor_order
    if main_first:
        order = ("trafilatura", *(name for name in order if name != "trafilatura"))
    used = "fallback"
    text = ""
    for name in order:
        text = extract_text(name, html)
        if text:
            used = name
            break
    if not text:
        text = strip_tags(html)
    return ExtractedDoc(url=url, text=normalize_text(text), extractor=used, raw_chars=len(html))


__all__ = [
    "ExtractedDoc",
    "dedupe_docs",
    "extract_and_normalize",
    "type_is_extracted",
]
