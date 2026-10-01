"""Hit-level cleanup: title/snippet normalization and near-duplicate removal."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import replace
from urllib.parse import urlsplit

from WebSearch.backend.normalize import normalize_text
from WebSearch.frontend.websearchers import SearchHit

#: " | ", " - ", en/em dash and middle dot between a title and a site name.
_SEPARATOR = re.compile(r"\s+[|–—·-]\s+")
_NON_ALNUM = re.compile(r"[\W_]+")
_TOKEN = re.compile(r"\w+")
_SHINGLE = 3
_BITS = 64


def _alnum(text: str) -> str:
    return _NON_ALNUM.sub("", text.casefold())


def _site_keys(url: str) -> set[str]:
    """Alphanumeric forms of the host labels (TLD excluded) and of the whole host."""
    try:
        host = (urlsplit(url).hostname or "").removeprefix("www.")
    except ValueError:
        return set()
    keys = {_alnum(label) for label in host.split(".")[:-1]}
    keys.add(_alnum(host))
    keys.discard("")
    return keys


def _strip_site_suffix(title: str, url: str) -> str:
    """Drop a trailing ``" | Site"`` when *Site* names the hit's own host."""
    matches = list(_SEPARATOR.finditer(title))
    if not matches:
        return title
    last = matches[-1]
    head, tail = title[: last.start()].rstrip(), title[last.end() :]
    return head if head and _alnum(tail) in _site_keys(url) else title


def normalize_hit(hit: SearchHit) -> SearchHit:
    """Canonicalize a hit's title and snippet.

    Both go through :func:`normalize_text`. A trailing site-name suffix is
    stripped from the title only when it matches the hit's own host, so titles
    that merely contain a separator are kept.

    Args:
        hit (SearchHit): Raw hit.

    Returns:
        SearchHit: Copy with cleaned ``title`` and ``snippet``.
    """
    title = _strip_site_suffix(normalize_text(hit.title), hit.url)
    return replace(hit, title=title, snippet=normalize_text(hit.snippet))


def _simhash(text: str) -> int | None:
    """64-bit SimHash over word 3-shingles; ``None`` when the text is too short."""
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


def near_dedupe(hits: Sequence[SearchHit], *, max_distance: int = 6) -> list[SearchHit]:
    """Drop hits whose title+snippet is a near-duplicate of an earlier hit.

    Similarity is the Hamming distance between 64-bit SimHashes. Hits with
    fewer than three words carry too little signal and are never merged. The
    earlier (better-ranked) hit survives and records the searcher ids of the
    hits merged into it in ``also_from``.

    Args:
        hits (Sequence[SearchHit]): Hits in rank order.
        max_distance (int): Largest Hamming distance counted as a duplicate.

    Returns:
        list[SearchHit]: Hits with near-duplicates removed, order preserved.
    """
    kept: list[SearchHit] = []
    prints: list[int | None] = []
    merged: list[list[str]] = []
    for hit in hits:
        fingerprint = _simhash(f"{hit.title} {hit.snippet}")
        match = None
        if fingerprint is not None:
            match = next(
                (
                    index
                    for index, other in enumerate(prints)
                    if other is not None
                    and (fingerprint ^ other).bit_count() <= max_distance
                ),
                None,
            )
        if match is None:
            kept.append(hit)
            prints.append(fingerprint)
            merged.append([])
        elif (
            hit.searcher_id != kept[match].searcher_id
            and hit.searcher_id not in merged[match]
        ):
            merged[match].append(hit.searcher_id)
    return [
        replace(hit, also_from=(*hit.also_from, *ids)) if ids else hit
        for hit, ids in zip(kept, merged, strict=True)
    ]


__all__ = ["near_dedupe", "normalize_hit"]
