"""Hit-level cleanup: title/snippet normalization and near-duplicate removal."""

from __future__ import annotations

lazy import functools
lazy import hashlib
lazy import re
lazy from collections.abc import Sequence
lazy from dataclasses import replace
lazy from urllib.parse import urlsplit

lazy from rapidfuzz import fuzz

lazy from WebSearch.Core.backend.normalize import (
    clean_snippet_noise,
    fingerprint_text,
    normalize_text,
)
lazy from WebSearch.Core.frontend.websearchers import SearchHit

#: " | ", " - ", en/em dash and middle dot between a title and a site name.
_SEPARATOR = re.compile(r"\s+[|–—·-]\s+")
_NON_ALNUM = re.compile(r"[\W_]+")
_TOKEN = re.compile(r"\w+")
_SHINGLE = 3
_BITS = 64
#: RapidFuzz ``token_set_ratio`` floor for title-only near-dupes in ``near_dedupe``.
#: Default ``is_fuzzy_duplicate_title`` is 88; search-engine title variants of the
#: same PEP land around 85, so the hit pipeline uses 80.
_TITLE_NEAR_THRESHOLD = 80.0
#: Query terms that carry no ranking signal (mirrors agent_tools._STOP_WORDS).
_STOP_WORDS = frozenset(
    "a an and are as at be by for from how in is it of on or that the to was what with".split()
)


def _simhash_bands(fingerprint: int, max_distance: int) -> tuple[tuple[int, int], ...]:
    """Partition bits so candidates within the threshold share at least one key."""
    count = max_distance + 1
    bands: list[tuple[int, int]] = []
    offset = 0
    for band in range(count):
        width = _BITS // count + (band < _BITS % count)
        bands.append((band, (fingerprint >> offset) & ((1 << width) - 1)))
        offset += width
    return tuple(bands)


def _alnum(text: str) -> str:
    return _NON_ALNUM.sub("", text.casefold())


@functools.cache
def _tld_extractor() -> object:
    """Offline tldextract extractor (bundled public-suffix list, no network)."""
    import tldextract

    return tldextract.TLDExtract(suffix_list_urls=())


def _site_keys(url: str) -> set[str]:
    """Alphanumeric forms of the registrable domain and host labels.

    Uses ``tldextract`` when installed so ``docs.python.org`` and
    ``python.org`` share the ``python.org`` registrable-domain key (and
    ``example.co.uk`` keeps its two-part suffix); falls back to the naive
    "drop the last label" heuristic when the package is missing.
    """
    try:
        host = (urlsplit(url).hostname or "").removeprefix("www.")
    except ValueError:
        return set()
    if not host:
        return set()
    keys: set[str] = set()
    try:
        ext = _tld_extractor()(host)
    except ImportError:
        ext = None
    if ext is not None and ext.domain:
        keys.update({_alnum(ext.domain), _alnum(f"{ext.domain}.{ext.suffix}")})
    else:
        keys.update(_alnum(label) for label in host.split(".")[:-1])
    keys.add(_alnum(host))
    keys.discard("")
    return keys


def _host_key(url: str) -> str:
    """www-stripped, case-folded hostname; empty when the URL has no host."""
    try:
        return (urlsplit(url).hostname or "").removeprefix("www.").casefold()
    except ValueError:
        return ""


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
    """
    title = _strip_site_suffix(normalize_text(hit.title), hit.url)
    cleaned_snippet = clean_snippet_noise(normalize_text(hit.snippet))
    return replace(hit, title=title, snippet=cleaned_snippet)


def is_fuzzy_duplicate_title(title_a: str, title_b: str, threshold: float = 88.0) -> bool:
    """Determine if two titles are near-duplicates using RapidFuzz token set ratio."""
    if not title_a or not title_b:
        return False
    return fuzz.token_set_ratio(title_a, title_b) >= threshold


def _query_terms(query: str) -> set[str]:
    """Content tokens from *query*: stop words and 1-char tokens dropped."""
    return {t for t in _TOKEN.findall(query.casefold()) if len(t) > 1 and t not in _STOP_WORDS}


def prune_snippet_to_query(snippet: str, query: str, max_chars: int = 320) -> str:
    """Keep query-overlapping sentences; drop filler even under *max_chars*.

    Sentence rank is term overlap, then RapidFuzz ``token_set_ratio`` (0–100)
    so paraphrases of the query win ties. Zero-overlap sentences are skipped
    once any overlapping sentence exists, matching ``hit_score`` stop-word
    rules so a lone "and" cannot keep a cookie-policy clause.
    """
    if not snippet:
        return snippet
    terms = _query_terms(query)
    if not terms:
        if len(snippet) <= max_chars:
            return snippet
        return snippet[:max_chars].rstrip() + "..."

    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", snippet) if p.strip()]
    if not parts:
        if len(snippet) <= max_chars:
            return snippet
        return snippet[:max_chars].rstrip() + "..."

    scored: list[tuple[int, float, str]] = []
    for part in parts:
        part_terms = {t for t in _TOKEN.findall(part.casefold()) if len(t) > 1}
        overlap = len(terms & part_terms)
        fuzz_s = fuzz.token_set_ratio(query, part, processor=str.casefold) if overlap else 0.0
        scored.append((overlap, fuzz_s, part))

    relevant = [item for item in scored if item[0] > 0]
    pool = relevant if relevant else scored

    selected: list[str] = []
    total_len = 0
    for overlap, _, part in sorted(pool, key=lambda item: (item[0], item[1]), reverse=True):
        if overlap == 0 and selected:
            break
        if total_len + len(part) + 1 <= max_chars:
            selected.append(part)
            total_len += len(part) + 1
        elif not selected:
            selected.append(part[:max_chars].rstrip() + "...")
            break

    if not selected:
        if len(snippet) <= max_chars:
            return snippet
        return snippet[:max_chars].rstrip() + "..."

    order_map = {part: i for i, part in enumerate(parts)}
    selected.sort(key=lambda p: order_map.get(p, 0))
    result = " ".join(selected)
    return result if len(result) <= max_chars else result[:max_chars].rstrip() + "..."


def hit_score(hit: SearchHit, query: str) -> float:
    """Relevance of *hit* for *query* in 0-1: share of query terms present.

    Used to choose which copy of a duplicated page to keep. Deliberately simple
    and dependency-free: this runs per duplicate group during fusion, so it must
    not cost an embedding call or a model round trip. Case-insensitive; query
    terms are de-duplicated, so repeating a word cannot inflate the score.
    Stop words and one-character tokens are ignored, matching
    :func:`WebSearch.Core.agents.agent_tools.relevance_score`, so filler like "and"/"the"
    cannot give an off-target hit a non-zero salience.

    Args:
        hit (SearchHit): Candidate hit.
        query (str): The user/orchestrator query the hits came from.

    Returns:
        float: Fraction of distinct query terms found in the title or snippet.
            ``0.0`` when the query has no usable terms, which makes callers fall
            back to their previous behaviour (keep the first copy).
    """
    terms = _query_terms(query)
    if not terms:
        return 0.0
    haystack = {t for t in _TOKEN.findall(f"{hit.title} {hit.snippet}".casefold()) if len(t) > 1}
    return len(terms & haystack) / len(terms)


def _simhash(text: str) -> int | None:
    """64-bit SimHash over word 3-shingles; ``None`` when the text is too short."""
    tokens = _TOKEN.findall(fingerprint_text(text))
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


def near_dedupe(hits: Sequence[SearchHit], *, max_distance: int = 3) -> list[SearchHit]:
    """Drop hits whose title+snippet is a near-duplicate of an earlier hit.

    Similarity is the Hamming distance between 64-bit SimHashes. Default
    ``max_distance`` is 3 (Go ``semblance`` HammingIndex). Hits with fewer
    than three words carry too little signal and are never merged. When
    SimHash does not fire and ``max_distance > 0``, RapidFuzz
    ``token_set_ratio`` on titles of at least three tokens still merges
    same-host provider variants of the same page. The earlier (better-ranked)
    hit survives and records the searcher ids of the hits merged into it in
    ``also_from``.

    Args:
        hits (Sequence[SearchHit]): Hits in rank order.
        max_distance (int): Largest Hamming distance counted as a duplicate.

    Returns:
        list[SearchHit]: Hits with near-duplicates removed, order preserved.
    """
    if max_distance < 0:
        raise ValueError("max_distance must be >= 0")
    kept: list[SearchHit] = []
    prints: list[int | None] = []
    merged: list[list[str]] = []
    band_index: dict[tuple[int, int], list[int]] = {}
    for hit in hits:
        fingerprint = _simhash(f"{hit.title} {hit.snippet}")
        match = None
        if fingerprint is not None:
            if max_distance >= _BITS:
                candidates = range(len(prints))
            else:
                candidate_ids: set[int] = set()
                for band in _simhash_bands(fingerprint, max_distance):
                    candidate_ids.update(band_index.get(band, ()))
                candidates = sorted(candidate_ids)
            for index in candidates:
                other = prints[index]
                if other is not None and (fingerprint ^ other).bit_count() <= max_distance:
                    match = index
                    break
        if match is None and max_distance > 0 and len(_TOKEN.findall(hit.title)) >= _SHINGLE:
            host = _host_key(hit.url)
            if host:
                for index, kept_hit in enumerate(kept):
                    if _host_key(kept_hit.url) != host:
                        continue
                    if len(_TOKEN.findall(kept_hit.title)) < _SHINGLE:
                        continue
                    if is_fuzzy_duplicate_title(
                        hit.title, kept_hit.title, threshold=_TITLE_NEAR_THRESHOLD
                    ):
                        match = index
                        break
        if match is None:
            kept.append(hit)
            prints.append(fingerprint)
            merged.append([])
            if fingerprint is not None and max_distance < _BITS:
                index = len(prints) - 1
                for band in _simhash_bands(fingerprint, max_distance):
                    band_index.setdefault(band, []).append(index)
        elif hit.searcher_id != kept[match].searcher_id and hit.searcher_id not in merged[match]:
            merged[match].append(hit.searcher_id)
    return [
        replace(hit, also_from=(*hit.also_from, *ids)) if ids else hit
        for hit, ids in zip(kept, merged, strict=True)
    ]


__all__ = [
    "hit_score",
    "is_fuzzy_duplicate_title",
    "near_dedupe",
    "normalize_hit",
    "prune_snippet_to_query",
]
