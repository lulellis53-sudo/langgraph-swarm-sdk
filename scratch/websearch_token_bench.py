"""Micro-benchmark: token savings of ``render_brief`` versus raw hit text.

Run with ``uv run python scratch/websearch_token_bench.py``.
"""

from __future__ import annotations

import random
import string
import time
from collections.abc import Sequence

from WebSearch.agent_tools import count_tokens, render_brief
from WebSearch.frontend.websearchers import SearchHit


def _random_word(length: int = 6) -> str:
    """Return a lowercase ASCII word of *length* characters."""
    return "".join(random.choices(string.ascii_lowercase, k=length))


def _make_hits(count: int, snippet_words: int = 40) -> list[SearchHit]:
    """Generate deterministic-ish fake search hits."""
    hits: list[SearchHit] = []
    for index in range(count):
        title = f"Result {_random_word()} {_random_word()}"
        snippet = " ".join(_random_word() for _ in range(snippet_words))
        hits.append(
            SearchHit(
                title=title,
                url=f"https://example.com/page{index}",
                snippet=snippet,
                searcher_id="bench",
            )
        )
    return hits


def _raw_text(hits: Sequence[SearchHit]) -> str:
    """Concatenate titles, URLs and snippets without any budget trimming."""
    return "\n\n".join(f"{hit.title}\n{hit.url}\n{hit.snippet}" for hit in hits)


def main() -> int:
    """Run the benchmark and print token counts and timings."""
    random.seed(42)
    hits = _make_hits(count=30, snippet_words=50)
    raw = _raw_text(hits)
    raw_tokens = count_tokens(raw)

    budgets = [100, 200, 400, 800]
    print(f"{'budget':>8} {'brief_tokens':>14} {'saved':>10} {'pct':>8} {'ms':>10}")
    for budget in budgets:
        started = time.perf_counter()
        brief = render_brief(hits, max_tokens=budget)
        elapsed_ms = (time.perf_counter() - started) * 1000
        brief_tokens = count_tokens(brief)
        saved = raw_tokens - brief_tokens
        pct = (saved / raw_tokens) * 100 if raw_tokens else 0.0
        print(f"{budget:>8} {brief_tokens:>14} {saved:>10} {pct:>7.1f}% {elapsed_ms:>9.2f}")

    print(f"\nraw_tokens: {raw_tokens}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
