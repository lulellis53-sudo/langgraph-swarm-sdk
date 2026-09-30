"""Tokenizer budgets so prompts stay under a hard token cap.

Default counting uses **tiktoken** (``cl100k_base``). Pass a Hugging Face
``tokenizers.Tokenizer`` (or a tiktoken ``Encoding``) for an explicit backend.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Protocol

from tokenizers import Tokenizer
from tokenizers.pre_tokenizers import Whitespace

_WHITESPACE = Whitespace()
_DEFAULT_TIKTOKEN = "cl100k_base"
_ENCODING_CACHE: dict[str, Any] = {}
_ENCODING_MISSING: set[str] = set()
_COUNT_CACHE: dict[tuple[int, int], int] = {}
_COUNT_CACHE_MAX = 512
_COUNT_LOCK = threading.Lock()


class _HasEncode(Protocol):
    """Anything with an ``encode`` method (HF Tokenizer or tiktoken Encoding)."""

    def encode(self, text: str, /, *args: Any, **kwargs: Any) -> Any: ...


def _tiktoken_encoding(name: str = _DEFAULT_TIKTOKEN) -> Any | None:
    """Load and cache a tiktoken encoding, or ``None`` if unavailable.

    Args:
        name: Encoding name (default ``cl100k_base``).

    Returns:
        A tiktoken ``Encoding``, or ``None`` when the package is missing or the
        vocabulary file cannot be downloaded.
    """
    if name in _ENCODING_CACHE:
        return _ENCODING_CACHE[name]
    if name in _ENCODING_MISSING:
        return None
    try:
        import tiktoken
    except ImportError:
        _ENCODING_MISSING.add(name)
        return None
    try:
        encoding = tiktoken.get_encoding(name)
    except Exception:
        # Offline / first-download failure → whitespace fallback (retry next call).
        return None
    _ENCODING_CACHE[name] = encoding
    return encoding


def _count_with(tokenizer: _HasEncode, text: str) -> int:
    """Count tokens using ``tokenizer.encode``.

    Args:
        tokenizer: HF Tokenizer or tiktoken Encoding.
        text: Input text.

    Returns:
        Number of token ids.
    """
    encoded = tokenizer.encode(text)
    ids = getattr(encoded, "ids", None)
    if ids is not None:
        return len(ids)
    return len(encoded)


def count_text(text: str, tokenizer: _HasEncode | None = None) -> int:
    """Count tokens in ``text``.

    Prefer ``tokenizer`` when given; otherwise tiktoken ``cl100k_base``; finally
    whitespace pre-tokenization as a last-resort fallback.

    Args:
        text: Input text (empty string counts as 0).
        tokenizer: Optional HF Tokenizer or tiktoken Encoding.

    Returns:
        Non-negative token count.
    """
    if not text:
        return 0
    key = (hash(text), id(tokenizer) if tokenizer is not None else 0)
    cached = _COUNT_CACHE.get(key)
    if cached is not None:
        return cached
    if tokenizer is not None:
        count = _count_with(tokenizer, text)
    else:
        encoding = _tiktoken_encoding()
        if encoding is not None:
            count = _count_with(encoding, text)
        else:
            count = len(_WHITESPACE.pre_tokenize_str(text))
    with _COUNT_LOCK:
        if len(_COUNT_CACHE) >= _COUNT_CACHE_MAX:
            for stale in list(_COUNT_CACHE)[: _COUNT_CACHE_MAX // 2]:
                del _COUNT_CACHE[stale]
        _COUNT_CACHE[key] = count
    return count


@dataclass(frozen=True)
class PackedPrompt:
    """System + user prompt pair packed under a token budget.

    Attributes:
        system: Stable system prompt (always non-empty after packing).
        user: Optional user/context body (may be empty).
    """

    system: str
    user: str

    @property
    def prefix(self) -> str:
        """Stable, cache-friendly part of the prompt."""
        return self.system

    @property
    def suffix(self) -> str:
        """Variable part of the prompt (may be empty)."""
        return self.user

    @property
    def text(self) -> str:
        """Full prompt text (``system`` alone, or ``system\\nuser``)."""
        if self.user:
            return f"{self.system}\n{self.user}"
        return self.system


class TokenBudget:
    """Keep a stable system prompt, then fill remaining room with newest turns.

    Attributes:
        max_tokens: Hard cap for the packed prompt.
        tool_cap: Per-line cap for memory/turn lines.
        tokenizer: Optional explicit tokenizer; default uses tiktoken.
    """

    def __init__(
        self,
        *,
        max_tokens: int = 2048,
        tool_cap: int = 128,
        tokenizer: Tokenizer | _HasEncode | None = None,
    ) -> None:
        """Initialize a packing budget.

        Args:
            max_tokens: Maximum tokens for the packed prompt (must be >= 1).
            tool_cap: Max tokens per memory/turn line.
            tokenizer: Optional HF Tokenizer or tiktoken Encoding.

        Raises:
            ValueError: If ``max_tokens`` is less than 1.
        """
        if max_tokens < 1:
            raise ValueError("max_tokens must be >= 1")
        self.max_tokens = max_tokens
        self.tool_cap = tool_cap
        self.tokenizer = tokenizer

    def count(self, text: str) -> int:
        """Count tokens with this budget's tokenizer.

        Args:
            text: Input text.

        Returns:
            Token count.
        """
        return count_text(text, self.tokenizer)

    def pack(self, *, system: str, memories: list[str], turns: list[str]) -> PackedPrompt:
        """Pack system, memories, and newest turns under ``max_tokens``.

        Args:
            system: System prompt (stripped; falls back to ``"system"``).
            memories: Context lines (oldest first).
            turns: Conversation turns (newest preferred when space is tight).

        Returns:
            A ``PackedPrompt`` whose ``.text`` fits ``max_tokens``.
        """
        system_text = self._fit_system(system)
        memories_fit = self._take(system_text, [], self._lines("memory: ", memories))
        turns_fit = self._take_newest(system_text, memories_fit, self._lines("turn: ", turns))
        user_parts = memories_fit + turns_fit
        user = "\n".join(user_parts)
        packed = PackedPrompt(system=system_text, user=user)
        if self.count(packed.text) > self.max_tokens:
            packed = PackedPrompt(system=system_text, user="")
        return packed

    def _fit_system(self, system: str) -> str:
        """Always return a non-empty system that fits ``max_tokens``.

        Args:
            system: Raw system prompt.

        Returns:
            Truncated or fallback system text.
        """
        text = system.strip() or "system"
        if self.count(text) <= self.max_tokens:
            return text
        truncated = self.truncate(text, self.max_tokens)
        if truncated:
            return truncated
        for fallback in ("s", ".", "x"):
            if self.count(fallback) <= self.max_tokens:
                return fallback
        return "s"

    def _lines(self, prefix: str, items: list[str]) -> list[str]:
        lines: list[str] = []
        for item in items:
            body = item.strip()
            if not body:
                continue
            lines.append(self.truncate(f"{prefix}{body}", self.tool_cap))
        return lines

    def _take(self, system_text: str, prior: list[str], lines: list[str]) -> list[str]:
        chosen = list(prior)
        for line in lines:
            fitted = self._fit(system_text, chosen, line, append=True)
            if fitted:
                chosen.append(fitted)
        return chosen

    def _take_newest(self, system_text: str, memories: list[str], turns: list[str]) -> list[str]:
        chosen: list[str] = []
        for line in reversed(turns):
            fitted = self._fit(system_text, memories + chosen, line, append=False)
            if fitted:
                chosen.insert(0, fitted)
        return chosen

    def _fit(self, system_text: str, parts: list[str], line: str, *, append: bool) -> str | None:
        def assembled(piece: str) -> str:
            ordered = [*parts, piece] if append else [piece, *parts]
            return PackedPrompt(system=system_text, user="\n".join(ordered)).text

        if self.count(assembled(line)) <= self.max_tokens:
            return line
        best: str | None = None
        lo = 0
        hi = len(line)
        while lo <= hi:
            mid = (lo + hi) // 2
            piece = line[:mid].rstrip()
            if piece and self.count(assembled(piece)) <= self.max_tokens:
                best = piece
                lo = mid + 1
            else:
                hi = mid - 1
        return best

    def truncate(self, text: str, limit: int) -> str:
        """Longest prefix of ``text`` that fits ``limit`` tokens.

        Binary search over prefix lengths; whitespace at the cut is stripped.
        Public because prompt builders outside this class (e.g. workers) fit
        user text into the room the system prompt leaves over.

        Args:
            text: Input text.
            limit: Token ceiling for the returned prefix.

        Returns:
            The longest prefix whose token count is ``<= limit`` (``""`` when
            ``limit`` is non-positive).
        """
        if limit <= 0:
            return ""
        if self.count(text) <= limit:
            return text
        best = ""
        lo = 0
        hi = len(text)
        while lo <= hi:
            mid = (lo + hi) // 2
            piece = text[:mid].rstrip()
            if self.count(piece) <= limit:
                best = piece
                lo = mid + 1
            else:
                hi = mid - 1
        return best
