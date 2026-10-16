"""Ingest ``Agents/<Name>/`` folders into the shared store and search them."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from orchestration.embedding import Embedder
from orchestration.graph import SearchFn
from orchestration.vectorstore import SharedVectorStore

__all__ = ["chunk_markdown", "ingest_agents", "make_search"]

logger = logging.getLogger(__name__)
_HEADING = re.compile(r"(?m)^(?=#{1,6}\s)")
_BLANK_LINE = re.compile(r"\n\s*\n")


def chunk_markdown(text: str, max_chars: int = 1200) -> list[str]:
    """Split Markdown on headings, pack paragraphs up to ``max_chars``, hard-split the rest.

    Args:
        text: Markdown source.
        max_chars: Maximum characters per chunk (must be positive).

    Returns:
        Non-empty chunks in document order; blank input gives ``[]``.

    Raises:
        ValueError: If ``max_chars`` is not positive.
    """
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    chunks: list[str] = []
    for section in _HEADING.split(text):
        current = ""
        for paragraph in _BLANK_LINE.split(section.strip()):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            candidate = f"{current}\n\n{paragraph}" if current else paragraph
            if len(candidate) <= max_chars:
                current = candidate
                continue
            if current:
                chunks.append(current)
            while len(paragraph) > max_chars:
                chunks.append(paragraph[:max_chars])
                paragraph = paragraph[max_chars:]
            current = paragraph
        if current:
            chunks.append(current)
    return chunks


def ingest_agents(root: Path, store: SharedVectorStore, embedder: Embedder) -> dict[str, int]:
    """Add every agent folder's Markdown chunks to the one shared store.

    Args:
        root: Folder whose first-level subfolders are agents (for example ``Agents/``).
        store: Shared store; each agent gets its own id block.
        embedder: Must produce vectors of ``store.dim``.

    Returns:
        ``{agent: chunks added this call}``; agents with nothing new are omitted.
    """
    added: dict[str, int] = {}
    for folder in sorted(p for p in root.iterdir() if p.is_dir() and not p.is_symlink()):
        agent = folder.name
        if agent.startswith(("_", ".")):
            continue
        for path in sorted(folder.rglob("*.md")):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                logger.warning("skipping non-UTF-8 file %s", path)
                continue
            source = path.relative_to(root).as_posix()
            fresh = [
                (number, chunk)
                for number, chunk in enumerate(chunk_markdown(text))
                if not store.has_text(agent, chunk)
            ]
            if not fresh:
                continue
            vectors = embedder.embed([chunk for _, chunk in fresh])
            for (number, chunk), vector in zip(fresh, vectors, strict=True):
                store.add(agent, source, number, chunk, vector)
            added[agent] = added.get(agent, 0) + len(fresh)
    return added


def make_search(
    store: SharedVectorStore, embedder: Embedder, *, agent: str | None = None, k: int = 4
) -> SearchFn:
    """Build the ``SearchFn`` that the graph's researcher node calls.

    Args:
        store: Shared store.
        embedder: Query embedder (same one used for ingest).
        agent: Restrict to this agent's RAG, or ``None`` to search all agents.
        k: Hits to return.

    Returns:
        A function from query text to lines ``[source#chunk score] text``.
    """

    def search(query: str) -> str:
        if not query.strip():
            return ""
        vector = embedder.embed([query], query=True)[0]
        hits = store.search(vector, k=k, agent=agent)
        return "\n".join(f"[{h.source}#{h.chunk} {h.score:.3f}] {h.text}" for h in hits)

    return search
