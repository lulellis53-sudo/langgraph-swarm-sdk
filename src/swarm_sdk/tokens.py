"""Tokenizer budgets so prompts stay under a hard token cap."""

from dataclasses import dataclass

from tokenizers import Tokenizer
from tokenizers.pre_tokenizers import Whitespace

_WHITESPACE = Whitespace()


def count_text(text: str, tokenizer: Tokenizer | None = None) -> int:
    if not text:
        return 0
    if tokenizer is not None:
        return len(tokenizer.encode(text).ids)
    return len(_WHITESPACE.pre_tokenize_str(text))


@dataclass(frozen=True)
class PackedPrompt:
    system: str
    user: str

    @property
    def text(self) -> str:
        if self.user:
            return f"{self.system}\n{self.user}"
        return self.system


class TokenBudget:
    """Keep a stable system prompt, then fill remaining room with newest turns."""

    def __init__(
        self,
        *,
        max_tokens: int = 2048,
        tool_cap: int = 128,
        tokenizer: Tokenizer | None = None,
    ) -> None:
        if max_tokens < 1:
            raise ValueError("max_tokens must be >= 1")
        self.max_tokens = max_tokens
        self.tool_cap = tool_cap
        self.tokenizer = tokenizer

    def count(self, text: str) -> int:
        return count_text(text, self.tokenizer)

    def pack(self, *, system: str, memories: list[str], turns: list[str]) -> PackedPrompt:
        system_text = system.strip() or "system"
        if self.count(system_text) > self.max_tokens:
            system_text = self._truncate(system_text, self.max_tokens)
        memories_fit = self._take(system_text, [], self._lines("memory: ", memories))
        turns_fit = self._take_newest(system_text, memories_fit, self._lines("turn: ", turns))
        user_parts = memories_fit + turns_fit
        user = "\n".join(user_parts)
        packed = PackedPrompt(system=system_text, user=user)
        if self.count(packed.text) > self.max_tokens:
            packed = PackedPrompt(system=self._truncate(system_text, self.max_tokens), user="")
        return packed

    def _lines(self, prefix: str, items: list[str]) -> list[str]:
        lines: list[str] = []
        for item in items:
            body = item.strip()
            if not body:
                continue
            lines.append(self._truncate(f"{prefix}{body}", self.tool_cap))
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

    def _truncate(self, text: str, limit: int) -> str:
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
