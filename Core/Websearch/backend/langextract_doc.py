"""Structured information extraction with source grounding (LangExtract).

Wraps `google/langextract <https://github.com/google/langextract>`_ (``lx.extract``)
so crawled text can yield typed fields whose spans are anchored back to the
source via character intervals — the grounding pass drops hallucinated spans
(``char_interval is None``). The heavy LLM SDK is imported lazily; the pure
:func:`grounded_extractions_to_dicts` converter is offline-testable without it.
"""

from __future__ import annotations

lazy import logging
lazy from collections.abc import Mapping, Sequence
lazy from typing import Any

logger = logging.getLogger(__name__)

#: Recommended LangExtract default (their docs: strong schema-constrained quality).
DEFAULT_MODEL_ID = "gemini-3.5-flash"


def grounded_extractions_to_dicts(
    extractions: Sequence[Any],
    *,
    source_text: str = "",
) -> list[dict[str, Any]]:
    """Flatten LangExtract extractions into JSON-ready, source-grounded dicts.

    Each output row carries the extraction class, text, attributes, character
    interval, and — when *source_text* is given — the verbatim ``quote`` sliced
    from that interval. Nested ``extractions`` become a child ``extractions``
    list. Pure function: works on any duck-typed objects exposing
    ``extraction_class``/``extraction_text``/``attributes``/``char_interval``,
    so tests need no LLM or the langextract package.

    Args:
        extractions (Sequence[Any]): Top-level extraction objects (may be empty).
        source_text (str): Original text; enables verbatim quote slicing.

    Returns:
        list[dict[str, Any]]: JSON-ready rows with ``grounded`` flags.
    """
    rows: list[dict[str, Any]] = []
    for item in extractions or ():
        interval = getattr(item, "char_interval", None)
        start = getattr(interval, "start_pos", None) if interval is not None else None
        end = getattr(interval, "end_pos", None) if interval is not None else None
        quote = source_text[start:end] if source_text and start is not None and end else None
        row: dict[str, Any] = {
            "class": getattr(item, "extraction_class", "") or "",
            "text": getattr(item, "extraction_text", "") or quote or "",
            "attributes": dict(getattr(item, "attributes", None) or {}),
            "start_pos": start,
            "end_pos": end,
            "quote": quote,
            "grounded": start is not None and end is not None,
        }
        children = grounded_extractions_to_dicts(
            getattr(item, "extractions", None) or (), source_text=source_text
        )
        if children:
            row["extractions"] = children
        rows.append(row)
    return rows


def extract_fields(
    text: str,
    prompt_description: str,
    *,
    model_id: str = DEFAULT_MODEL_ID,
    examples: Sequence[Any] | None = None,
    max_char_buffer: int = 1000,
    extra: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run LangExtract over *text* and return grounded extraction dicts.

    Requires the ``langextract`` extra (``uv sync --extra langextract``) and the
    model provider's credentials (``GEMINI_API_KEY`` for the default Gemini
    model). Failed/ungrounded spans are logged and marked ``grounded: false``
    rather than silently trusted.

    Args:
        text (str): Source document text (already extracted/normalized).
        prompt_description (str): Task prompt describing fields to extract.
        model_id (str): LangExtract model id (``provider:model`` style names ok).
        examples (Sequence[Any] | None): Optional ``lx.data.Examples`` few-shots.
        max_char_buffer (int): Chunk size for long documents (LangExtract option).
        extra (Mapping[str, Any] | None): Extra kwargs forwarded to ``lx.extract``.

    Returns:
        list[dict[str, Any]]: Grounded extraction rows (see converter).

    Raises:
        OSError: If the langextract package is not installed.
    """
    if not text.strip():
        return []
    try:
        import langextract as lx
    except ImportError as exc:
        raise OSError("langextract not installed (uv sync --extra langextract)") from exc

    kwargs: dict[str, Any] = {
        "text_or_documents": text,
        "prompt_description": prompt_description,
        "model_id": model_id,
        "max_char_buffer": max_char_buffer,
    }
    if examples:
        kwargs["examples"] = list(examples)
    if extra:
        kwargs.update(extra)
    result = lx.extract(**kwargs)
    rows = grounded_extractions_to_dicts(
        getattr(result, "extractions", None) or (), source_text=text
    )
    ungrounded = sum(1 for row in rows if not row["grounded"])
    if ungrounded:
        logger.warning("langextract: %d/%d extractions ungrounded", ungrounded, len(rows))
    return rows


__all__ = ["DEFAULT_MODEL_ID", "extract_fields", "grounded_extractions_to_dicts"]
