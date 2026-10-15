"""Core implementation of the WebSearch pipeline (moved from the package root).

Layout:

- ``frontend`` — search providers, fan-out/RRF fusion, hit normalization
- ``midend`` — crawler failover (httpx … playwright/crawlee) and scraping
- ``backend`` — prefilters, extractors, normalization, docs, semantic store
- ``agents`` — agent/tool-calling surfaces (LangChain tools, MCP, tokens)
- ``app`` — CLI, FastAPI, doctor, digest, browser agent, entrypoints
- ``shared`` — cross-cutting helpers (URL repeater)
"""

from __future__ import annotations
