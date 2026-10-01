"""Text normalization applied after every extractor."""

from __future__ import annotations

import html as html_lib
import re
import unicodedata

_WS = re.compile(r"\s+")


#: Zero-width chars, BOM and C0 controls (tab/newline/CR are kept for line splitting).
_INVISIBLE = re.compile(r"[\u200b-\u200f\u2060\ufeff\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def normalize_text(text: str) -> str:
    """Canonicalize extracted text. Shared post-step for every extractor.

    NFKC-normalizes, unescapes HTML entities, drops invisible/control chars,
    collapses whitespace per line, and removes repeated lines (menus, footers,
    cookie banners) case-insensitively, keeping the first occurrence.

    Args:
        text (str): Raw extracted text.

    Returns:
        str: Single-line normalized text.
    """
    text = _INVISIBLE.sub("", html_lib.unescape(unicodedata.normalize("NFKC", text)))
    seen: set[str] = set()
    kept: list[str] = []
    for line in text.splitlines():
        clean = _WS.sub(" ", line).strip()
        key = clean.casefold()
        if clean and key not in seen:
            seen.add(key)
            kept.append(clean)
    return " ".join(kept)


__all__ = ["normalize_text"]
