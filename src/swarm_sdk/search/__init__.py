"""Search SDK module providing web and AI search engines.

``PerplexitySearchEngine`` pulls in Playwright, so the import is deferred:
importing :mod:`swarm_sdk.search` must work without optional browsers.
"""

from __future__ import annotations

from typing import Any

__all__ = ["PerplexitySearchEngine", "ask_perplexity"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from swarm_sdk.search.perplexity import PerplexitySearchEngine, ask_perplexity

        return {"PerplexitySearchEngine": PerplexitySearchEngine, "ask_perplexity": ask_perplexity}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
