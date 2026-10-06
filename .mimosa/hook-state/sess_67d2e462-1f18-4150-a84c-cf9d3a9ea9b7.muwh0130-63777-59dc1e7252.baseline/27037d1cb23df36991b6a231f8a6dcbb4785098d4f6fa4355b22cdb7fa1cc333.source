"""Redact secret-looking tokens from text before it leaves the process."""

from __future__ import annotations

import re

__all__ = ["REDACTED", "SECRET_RE", "redact_secrets"]

REDACTED = "[REDACTED]"

# Vendor key shapes seen in the registry providers (Google, OpenAI-style, GitHub, xAI, Groq,
# NVIDIA, Tavily, Hugging Face). Minimum lengths keep short doc placeholders from matching.
_KEY_SHAPES = (
    r"AQ\.[A-Za-z0-9_\-]{20,}",
    r"AIza[A-Za-z0-9_\-]{30,}",
    r"sk-[A-Za-z0-9_\-]{20,}",
    r"gh[pousr]_[A-Za-z0-9]{30,}",
    r"xai-[A-Za-z0-9]{20,}",
    r"gsk_[A-Za-z0-9]{20,}",
    r"nvapi-[A-Za-z0-9_\-]{20,}",
    r"tvly-[A-Za-z0-9_\-]{16,}",
    r"hf_[A-Za-z0-9]{30,}",
)
SECRET_RE = re.compile("|".join(f"(?:{shape})" for shape in _KEY_SHAPES))
_ASSIGNMENT_RE = re.compile(
    r"\b([A-Z][A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*)\s*=\s*\S+"
)


def redact_secrets(text: str) -> str:
    """Return ``text`` with key-shaped tokens and ``NAME_KEY=value`` assignments masked."""
    text = _ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}={REDACTED}", text)
    return SECRET_RE.sub(REDACTED, text)
