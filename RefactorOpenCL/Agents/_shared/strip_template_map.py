#!/usr/bin/env python3
"""Remove TEMPLATE map blockquote from Agents/*/AGENTS.md."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP = {"antigravity-imported", "benchmark", "tests", "_shared"}
PATTERN = re.compile(
    r"\n> \*\*TEMPLATE map:\*\*[^\n]*\n(?:\n)?",
    re.MULTILINE,
)


def main() -> None:
    n = 0
    for path in sorted(ROOT.glob("*/AGENTS.md")):
        if path.parent.name in SKIP:
            continue
        text = path.read_text(encoding="utf-8")
        new = PATTERN.sub("\n", text)
        if new != text:
            path.write_text(new, encoding="utf-8")
            n += 1
            print(path.relative_to(ROOT.parent))
    print(f"stripped {n} files")


if __name__ == "__main__":
    main()
