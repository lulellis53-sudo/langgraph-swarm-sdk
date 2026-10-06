"""Rewrite swarm_sdk module paths. Usage: rewrite.py [--dry-run] old=new [old=new ...]

`old`/`new` are dotted prefixes, e.g. swarm_sdk.execution=swarm_sdk.runtime.
Both `swarm_sdk.a.b` and `swarm_sdk/a/b` spellings are rewritten.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SKIP_DIRS = {".git", ".venv", "__pycache__", ".ruff_cache", ".pytest_cache", ".hypothesis", "target", "node_modules"}
SKIP_PREFIXES = (".superpowers", "docs/superpowers", "scratch/merge_tools", "tests/test_package_layout.py")
SKIP_NAMES = {"uv.lock"}


def build_patterns(pairs: list[tuple[str, str]]) -> list[tuple[re.Pattern[str], str]]:
    patterns: list[tuple[re.Pattern[str], str]] = []
    for old, new in pairs:
        # Not followed by an identifier char, so `swarm_sdk.math` never matches `swarm_sdk.mathx`.
        patterns.append((re.compile(re.escape(old) + r"(?![A-Za-z0-9_])"), new))
        old_slash, new_slash = old.replace(".", "/"), new.replace(".", "/")
        patterns.append((re.compile(re.escape(old_slash) + r"(?![A-Za-z0-9_])"), new_slash))
    return patterns


def is_path_skipped(rel_path: str, skip_prefixes: tuple[str, ...]) -> bool:
    """Check if a path is skipped by prefix: exact match or starts with prefix + '/'."""
    for prefix in skip_prefixes:
        if rel_path == prefix or rel_path.startswith(prefix + "/"):
            return True
    return False


def main(argv: list[str]) -> int:
    # Reject unknown flags before touching any file
    for arg in argv:
        if arg.startswith("--") and arg != "--dry-run":
            print(f"error: unknown flag: {arg}", file=sys.stderr)
            return 2

    dry = "--dry-run" in argv
    pairs = [(a.split("=", 1)[0], a.split("=", 1)[1]) for a in argv if "=" in a]
    if not pairs:
        print(__doc__)
        return 2
    patterns = build_patterns(pairs)
    root = Path.cwd()
    changed = 0
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        rel_str = str(rel)
        if (
            not path.is_file()
            or rel_str in SKIP_NAMES
            or any(part in SKIP_DIRS for part in rel.parts)
            or is_path_skipped(rel_str, SKIP_PREFIXES)
        ):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Skip binary files silently
            continue
        new_text = text
        for pattern, replacement in patterns:
            new_text = pattern.sub(replacement, new_text)
        if new_text != text:
            changed += 1
            print(rel)
            if not dry:
                path.write_text(new_text, encoding="utf-8")
    print(f"{changed} file(s) {'would change' if dry else 'changed'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
