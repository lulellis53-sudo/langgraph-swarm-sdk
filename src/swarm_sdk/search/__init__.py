"""Web and AI search engines.

Re-exports the Perplexity engine so ``swarm_sdk.search`` is the single entry
point. Playwright (the ``scrape`` extra) is required by that engine.
"""

from __future__ import annotations

from src.swarm_sdk.search.perplexity import PerplexitySearchEngine, ask_perplexity

__all__ = ["PerplexitySearchEngine", "ask_perplexity"]
