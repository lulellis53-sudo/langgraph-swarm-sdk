"""Render a compiled LangGraph graph to Mermaid text and files (offline)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

__all__ = ["render_mermaid", "write_graph_files"]


class _DrawableGraph(Protocol):
    """Anything with LangGraph's ``get_graph().draw_mermaid()``."""

    def get_graph(self): ...


def render_mermaid(graph: _DrawableGraph) -> str:
    """Return the Mermaid source of a compiled graph.

    Args:
        graph: A compiled LangGraph graph exposing ``get_graph()``.

    Returns:
        Mermaid flowchart text. No network call is made (PNG rendering via
        mermaid.ink is deliberately not used).
    """
    return graph.get_graph().draw_mermaid()


def write_graph_files(graph: _DrawableGraph, directory: Path, name: str = "graph") -> list[Path]:
    """Write ``<name>.mmd`` and a Markdown wrapper ``<name>.md``.

    Args:
        graph: A compiled LangGraph graph.
        directory: Output folder; created if missing.
        name: File stem. Must not contain a path separator.

    Returns:
        ``[<name>.mmd, <name>.md]`` as paths.

    Raises:
        ValueError: If ``name`` is empty or contains a path separator.
    """
    if not name or Path(name).name != name or name in {".", ".."}:
        raise ValueError(f"name must be a plain file stem, got {name!r}")
    text = render_mermaid(graph)
    directory.mkdir(parents=True, exist_ok=True)
    mmd = directory / f"{name}.mmd"
    md = directory / f"{name}.md"
    mmd.write_text(text, encoding="utf-8")
    md.write_text(f"```mermaid\n{text}\n```\n", encoding="utf-8")
    return [mmd, md]
