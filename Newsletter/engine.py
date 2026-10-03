"""Newsletter digest builder (offline MVP)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

__all__ = ["DigestResult", "SourceSnippet", "build_digest"]


@dataclass(frozen=True, slots=True)
class SourceSnippet:
    """One item in a digest."""

    title: str
    body: str
    url: str = ""


@dataclass(frozen=True, slots=True)
class DigestResult:
    """Markdown digest plus summary metadata."""

    title: str
    markdown: str
    source_count: int
    word_count: int


def _normalize_line(text: str) -> str:
    return " ".join(text.split())


def build_digest(
    title: str,
    sources: Sequence[SourceSnippet],
    *,
    max_items: int = 50,
) -> DigestResult:
    """Merge snippets into Markdown; dedupe identical normalized lines."""
    if not title.strip():
        raise ValueError("title must be non-empty")
    if max_items < 1:
        raise ValueError("max_items must be at least 1")

    seen: set[str] = set()
    sections: list[str] = []
    for snippet in list(sources)[:max_items]:
        heading = snippet.title.strip() or "Untitled"
        body = snippet.body.strip()
        if not body:
            continue
        key = _normalize_line(body).lower()
        if key in seen:
            continue
        seen.add(key)
        block = f"## {heading}\n\n{body}"
        if snippet.url.strip():
            block += f"\n\nSource: {snippet.url.strip()}"
        sections.append(block)

    markdown = f"# {title.strip()}\n\n" + "\n\n---\n\n".join(sections)
    words = len(markdown.split())
    return DigestResult(
        title=title.strip(),
        markdown=markdown,
        source_count=len(sections),
        word_count=words,
    )
