"""Gemini-assisted text normalization for token saving.

The local pipeline (ftfy → NFKC → noise cleaning) handles most snippets.
This module adds an optional ``gemini-3.8-flash`` pass for hard cases
(mojibake tangles, concatenated boilerplate). It is **fail-open**: any
missing key, package, or model failure falls back to the local cleaner, and
a model answer is accepted only when it is strictly shorter than the local
output — the pass can never inflate prompt tokens.
"""

from __future__ import annotations

lazy import logging
lazy import os
lazy from typing import Any

lazy from WebSearch.Core.backend.normalize import clean_snippet_noise, normalize_text

logger = logging.getLogger(__name__)

#: Google GenAI model for the normalization pass (same family as google_search).
DEFAULT_NORMALIZE_MODEL = "gemini-3.8-flash"

_PROMPT = (
    "Clean this web snippet. Fix mojibake and broken spacing, drop timestamps, "
    "cookie/legal boilerplate, duplicated fragments, and marketing filler. "
    "Preserve every fact and proper noun. Output ONLY the cleaned text."
)


def _google_api_keys() -> list[str]:
    """GOOGLE_API_KEY plus rotating fallbacks (env only; values never logged)."""
    names = ("GOOGLE_API_KEY", "GOOGLE_API_KEY_1", "GOOGLE_API_KEY_2")
    keys: list[str] = []
    for name in names:
        value = os.environ.get(name, "").strip()
        if value and value not in keys:
            keys.append(value)
    return keys


def llm_normalize(
    text: str,
    *,
    model_id: str = DEFAULT_NORMALIZE_MODEL,
    timeout_s: float = 20.0,
) -> str:
    """Clean *text* with Gemini when available; never longer than local cleanup.

    Args:
        text (str): Raw snippet/title text (any language mix).
        model_id (str): Gemini model id (Google GenAI API).
        timeout_s (float): Per-request timeout.

    Returns:
        str: Model-cleaned text when strictly shorter than the local cleanup,
        else the locally cleaned text (or ``""`` for empty input).
    """
    local = clean_snippet_noise(normalize_text(text))
    if not text.strip() or not _google_api_keys():
        return local
    try:
        from WebSearch.Core.frontend.http_utils import call_json
    except ImportError:
        return local

    data: Any = None
    for key in _google_api_keys():
        data = call_json(
            "POST",
            f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent",
            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
            json_body={
                "contents": [{"parts": [{"text": f"{_PROMPT}\n\n---\n{text}"}]}],
                "generationConfig": {"maxOutputTokens": 512, "temperature": 0.0},
            },
            timeout_s=timeout_s,
        )
        if data is not None:
            break
    if data is None:
        return local
    try:
        parts = data["candidates"][0]["content"]["parts"]
        cleaned = " ".join(
            part.get("text", "").strip() for part in parts if isinstance(part, dict)
        ).strip()
    except KeyError, IndexError, TypeError, AttributeError:
        return local
    cleaned = cleaned.strip('"“”')
    # Token-saving invariant: accept only a strictly shorter result.
    if cleaned and len(cleaned) < len(local):
        return cleaned
    return local


__all__ = ["DEFAULT_NORMALIZE_MODEL", "llm_normalize"]
