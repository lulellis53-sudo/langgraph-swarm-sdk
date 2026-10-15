"""Token saver: pack scored hits into a token budget without losing the best.

Token counts are max(tiktoken cl100k_base, Qwen3-Embedding int8 tokenizer)
so a brief never overruns the LLM or the embedder. The packer is greedy by
score, dedupes by URL and near-duplicate snippets, and reports what it saved.
"""

from __future__ import annotations

import functools
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["TokenBudgetExceeded", "pack_hits", "estimate_tokens", "savings_report"]

_WORD_RE = re.compile(r"[a-z0-9]{3,}")
_ENCODING_NAME = "cl100k_base"
_DEFAULT_QWEN_DIR = Path.home() / "build" / "qwen3-embed"
#: Char fallback when shrinking an oversized snippet to a token budget.
_CHARS_PER_TOKEN = 4


class TokenBudgetExceeded(Exception):
    """Raised when a single item cannot fit an empty budget."""


def _qwen_tokenizer_path() -> Path | None:
    raw = os.environ.get("SWARM_QWEN_ONNX_DIR")
    roots = [Path(raw).expanduser()] if raw else []
    roots.append(_DEFAULT_QWEN_DIR)
    for root in roots:
        tok = root / "tokenizer.json"
        if tok.is_file():
            return tok
    return None


@functools.cache
def _tiktoken_encoding() -> object | None:
    try:
        import tiktoken
    except ImportError:
        return None
    try:
        return tiktoken.get_encoding(_ENCODING_NAME)
    except Exception:
        return None


@functools.cache
def _qwen_tokenizer() -> object | None:
    path = _qwen_tokenizer_path()
    if path is None:
        return None
    try:
        from tokenizers import Tokenizer
    except ImportError:
        return None
    tokenizer = Tokenizer.from_file(str(path))
    tokenizer.no_truncation()
    tokenizer.no_padding()
    return tokenizer


def _count_tiktoken(text: str) -> int:
    if not text:
        return 0
    encoding = _tiktoken_encoding()
    if encoding is None:
        return max(1, len(text) // 4)
    return len(encoding.encode(text, disallowed_special=()))


def _count_embedder(text: str) -> int:
    if not text:
        return 0
    tokenizer = _qwen_tokenizer()
    if tokenizer is None:
        return _count_tiktoken(text)
    encoded = tokenizer.encode(text)
    ids = getattr(encoded, "ids", encoded)
    return len(ids)


def estimate_tokens(text: str) -> int:
    """Count tokens: max of tiktoken cl100k_base and the Qwen int8 tokenizer."""
    if not text:
        return 0
    return max(_count_tiktoken(text), _count_embedder(text))


def _fit_to_budget(text: str, url: str, usable: int) -> tuple[str, int] | None:
    """Shrink ``text`` until text+url tokens fit ``usable``. None if it cannot."""
    url_tokens = estimate_tokens(url)
    keep_chars = max(0, (usable - url_tokens - 1) * _CHARS_PER_TOKEN)
    original = text
    while True:
        if keep_chars < len(original):
            candidate = original[:keep_chars].rstrip() + "..."
        else:
            candidate = original
        tokens = estimate_tokens(candidate) + url_tokens
        if tokens <= usable:
            return candidate, tokens
        if keep_chars <= 8:
            return None
        keep_chars //= 2


def _words(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def _boilerplate(kept_word_sets: list[set[str]]) -> set[str]:
    """Words that appear in most already-kept snippets are template noise,
    not evidence of duplication — comparing on them drops distinct deals
    that merely share phrasing ("oferta", "frete gratis", ...)."""
    if len(kept_word_sets) < 2:
        return set()
    threshold = max(2, int(len(kept_word_sets) * 0.6))
    counts: dict[str, int] = {}
    for words in kept_word_sets:
        for word in words:
            counts[word] = counts.get(word, 0) + 1
    return {word for word, count in counts.items() if count >= threshold}


def _is_near_duplicate(
    candidate: str, kept_word_sets: list[set[str]], threshold: float
) -> bool:
    if not kept_word_sets:
        return False
    boiler = _boilerplate(kept_word_sets)
    cand_words = _words(candidate) - boiler
    if not cand_words:
        # Nothing informative left: identical template text.
        return True
    for words in kept_word_sets:
        overlap = words - boiler
        if not overlap:
            continue
        union = cand_words | overlap
        if union and len(cand_words & overlap) / len(union) >= threshold:
            return True
    return False


@dataclass(slots=True)
class PackResult:
    """Outcome of one :func:`pack_hits` call."""

    kept: list[dict[str, Any]]
    dropped: list[dict[str, Any]]
    tokens_used: int
    tokens_dropped: int
    duplicates_dropped: int = 0
    notes: list[str] = field(default_factory=list)


def pack_hits(
    hits: list[dict[str, Any]],
    budget_tokens: int,
    *,
    text_key: str = "snippet",
    url_key: str = "url",
    score_key: str = "score",
    similarity_threshold: float = 0.8,
    reserve_tokens: int = 0,
    min_score: float | None = None,
    on_oversized: str = "error",
) -> PackResult:
    """Greedily pack ``hits`` (highest score first) into ``budget_tokens``.

    Args:
        hits: Dicts with at least ``text_key`` and ``url_key``; ``score_key``
            is optional (missing scores keep input order).
        budget_tokens: Total token budget for the packed output.
        similarity_threshold: Word-Jaccard at or above this counts a snippet
            as a near-duplicate of an already-kept hit and drops it.
        reserve_tokens: Budget withheld for prompt framing, not hits.
        min_score: Drop hits whose ``score_key`` is below this (0..1).
        on_oversized: ``error`` raises when one hit exceeds the usable budget;
            ``drop`` skips it; ``truncate`` shortens ``text_key`` until it fits.

    Returns:
        PackResult with kept/dropped hits and token accounting. Each kept
        hit gains ``"_tokens"`` and ``"_rank"`` keys.

    Raises:
        TokenBudgetExceeded: When ``reserve_tokens >= budget_tokens``, or a
            single hit is larger than the usable budget and ``on_oversized``
            is ``error``.
        ValueError: When ``on_oversized`` is not one of the known modes.
    """
    if on_oversized not in {"error", "drop", "truncate"}:
        raise ValueError("on_oversized must be 'error', 'drop', or 'truncate'")
    usable = budget_tokens - reserve_tokens
    if usable <= 0:
        raise TokenBudgetExceeded(
            f"reserve_tokens ({reserve_tokens}) must be below budget_tokens ({budget_tokens})"
        )

    def _score(hit: dict[str, Any]) -> float:
        value = hit.get(score_key)
        return float(value) if value is not None else 0.0

    ordered = sorted(hits, key=_score, reverse=True)
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    kept_word_sets: list[set[str]] = []
    used = 0
    duplicates = 0

    for hit in ordered:
        if min_score is not None and _score(hit) < min_score:
            dropped.append({**hit, "_drop_reason": "min_score"})
            continue
        text = str(hit.get(text_key, ""))
        url = str(hit.get(url_key, ""))
        tokens = estimate_tokens(text) + estimate_tokens(url)
        if tokens > usable:
            if on_oversized == "error":
                raise TokenBudgetExceeded(
                    f"single hit needs {tokens} tokens, usable budget is {usable}"
                )
            if on_oversized == "drop":
                dropped.append({**hit, "_drop_reason": "too_large"})
                continue
            fitted = _fit_to_budget(text, url, usable)
            if fitted is None:
                dropped.append({**hit, "_drop_reason": "too_large"})
                continue
            text, tokens = fitted
            hit = {**hit, text_key: text}
        if url in seen_urls:
            duplicates += 1
            dropped.append({**hit, "_drop_reason": "duplicate_url"})
            continue
        if _is_near_duplicate(text, kept_word_sets, similarity_threshold):
            duplicates += 1
            dropped.append({**hit, "_drop_reason": "near_duplicate"})
            continue
        if used + tokens > usable:
            dropped.append({**hit, "_drop_reason": "budget"})
            continue
        seen_urls.add(url)
        kept_word_sets.append(_words(text))
        used += tokens
        kept.append({**hit, "_tokens": tokens, "_rank": len(kept) + 1})

    return PackResult(
        kept=kept,
        dropped=dropped,
        tokens_used=used,
        tokens_dropped=sum(
            estimate_tokens(str(h.get(text_key, ""))) for h in dropped
        ),
        duplicates_dropped=duplicates,
    )


def savings_report(result: PackResult, original_count: int) -> str:
    """One-line human summary of a pack: kept, dropped, tokens, savings %."""
    total = result.tokens_used + result.tokens_dropped
    pct = (100 * result.tokens_dropped // total) if total else 0
    return (
        f"kept {len(result.kept)}/{original_count} hits, "
        f"{result.tokens_used} tokens used, "
        f"{result.tokens_dropped} saved ({pct}%), "
        f"{result.duplicates_dropped} duplicates"
    )
