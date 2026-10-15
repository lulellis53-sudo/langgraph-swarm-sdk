"""Console, table and panel helpers for the `low-swarm` CLI with a plain-text fallback."""

from __future__ import annotations

import re
import sys
from typing import Any

# -----------------------------------------------------------------------------
# Rich Console & Fallback Abstraction
# -----------------------------------------------------------------------------

try:
    from rich.console import Console as _RichConsole
    from rich.panel import Panel as _RichPanel
    from rich.syntax import Syntax as _RichSyntax
    from rich.table import Table as _RichTable

    _RICH_AVAILABLE = True
except ImportError:
    _RichConsole = None
    _RichPanel = None
    _RichSyntax = None
    _RichTable = None
    _RICH_AVAILABLE = False


_MARKUP_RE = re.compile(
    r"\[/?(?:bold|italic|underline|green|red|yellow|blue|cyan|magenta|dim|white)[^\]]*\]|\[/\]"
)


class PlainTable:
    """Lightweight plain-text table formatter fallback when Rich is unavailable."""

    def __init__(self, title: str = "") -> None:
        """Initialize an empty table with the given column headers."""
        self.title = title
        self.columns: list[str] = []
        self.rows: list[list[str]] = []

    def add_column(self, header: str, **kwargs: Any) -> None:
        """Add a column header."""
        self.columns.append(header)

    def add_row(self, *args: Any, **kwargs: Any) -> None:
        """Append one row of cells."""
        cleaned_cells = [_MARKUP_RE.sub("", str(a)) for a in args]
        self.rows.append(cleaned_cells)

    def __str__(self) -> str:
        """Render the table as aligned plain text."""
        lines: list[str] = []
        if self.title:
            lines.append(f"=== {self.title} ===")
        if not self.columns:
            return "\n".join(lines)

        col_widths = [len(c) for c in self.columns]
        for row in self.rows:
            for i, val in enumerate(row):
                if i < len(col_widths):
                    col_widths[i] = max(col_widths[i], len(val))

        header_line = " | ".join(c.ljust(col_widths[i]) for i, c in enumerate(self.columns))
        sep_line = "-+-".join("-" * col_widths[i] for i in range(len(self.columns)))
        lines.append(header_line)
        lines.append(sep_line)

        for row in self.rows:
            r_cells = [
                row[i].ljust(col_widths[i]) if i < len(row) else "".ljust(col_widths[i])
                for i in range(len(self.columns))
            ]
            lines.append(" | ".join(r_cells))

        return "\n".join(lines)


class PlainPanel:
    """Lightweight plain-text panel fallback when Rich is unavailable."""

    def __init__(self, content: Any, title: str = "", **kwargs: Any) -> None:
        """Initialize the panel with its title and body lines."""
        self.content = content
        self.title = title

    def __str__(self) -> str:
        """Render the panel content with Rich markup stripped."""
        content_str = str(self.content)
        cleaned = re.sub(
            r"\[/?(?:bold|italic|underline|green|red|yellow|blue|cyan|magenta|dim|white)[^\]]*\]",
            "",
            content_str,
        )
        hdr = f"[{self.title}]" if self.title else ""
        return f"+--- {hdr} ---+\n{cleaned}\n+---------------------------------+"


class PlainConsole:
    """Lightweight plain-text console fallback writing to stdout."""

    def __init__(self, file: Any = None) -> None:
        """Initialize the fallback console (no rich required)."""
        self.file = file or sys.stdout

    def print(self, *args: Any, **kwargs: Any) -> None:
        """Render the table to stdout."""
        if not args:
            print(file=self.file)
            return

        out_parts: list[str] = []
        for a in args:
            if isinstance(a, (PlainTable, PlainPanel)):
                out_parts.append(str(a))
            else:
                cleaned = _MARKUP_RE.sub("", str(a))
                out_parts.append(cleaned)
        print(" ".join(out_parts), file=self.file)

    def rule(self, title: str = "") -> None:
        """Render a horizontal rule."""
        if title:
            self.print(f"--- {title} ---")
        else:
            self.print("-" * 40)


def get_console() -> Any:
    """Returns Rich Console if installed, otherwise PlainConsole.

    Returns:
        Console instance capable of printing formatted output.
    """
    if _RICH_AVAILABLE and _RichConsole is not None:
        return _RichConsole(file=sys.stdout, highlight=False)
    return PlainConsole(file=sys.stdout)


def create_table(title: str = "") -> Any:
    """Creates a Rich Table if available, otherwise PlainTable.

    Args:
        title: Optional title displayed at top of table.

    Returns:
        Table instance (Rich Table or PlainTable fallback).
    """
    if _RICH_AVAILABLE and _RichTable is not None:
        return _RichTable(title=title, show_header=True)
    return PlainTable(title=title)


def create_panel(content: Any, title: str = "") -> Any:
    """Creates a Rich Panel if available, otherwise PlainPanel.

    Args:
        content: Inner renderable content or string to wrap in panel.
        title: Optional panel border title.

    Returns:
        Panel instance (Rich Panel or PlainPanel fallback).
    """
    if _RICH_AVAILABLE and _RichPanel is not None:
        return _RichPanel(content, title=title)
    return PlainPanel(content, title=title)


def create_syntax(code: str, lexer: str) -> Any | None:
    """Creates a Rich Syntax block if available, otherwise returns None.

    Args:
        code: Source code or diff text to syntax highlight.
        lexer: Language lexer identifier (e.g. 'diff', 'python').

    Returns:
        Rich Syntax instance if available, or None if rich is absent.
    """
    if _RICH_AVAILABLE and _RichSyntax is not None:
        return _RichSyntax(code, lexer)
    return None
