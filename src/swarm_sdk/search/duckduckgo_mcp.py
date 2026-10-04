#!/usr/bin/env python3

"""
DuckDuckGo Websearch MCP Server.
Provides tools to search DuckDuckGo, fetch instant encyclopedic answers,
and extract full webpage markdown content without API keys.
Compatible with MCP 1.x (FastMCP) and MCP 2.x (MCPServer).
"""

from __future__ import annotations

import json

try:
    from mcp.server.mcpserver import MCPServer

    server = MCPServer("duckduckgo-search")
except ImportError, ModuleNotFoundError:
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("duckduckgo-search")

from swarm_sdk.search.duckduckgo import (
    duckduckgo_instant_answer,
    duckduckgo_search,
    extract_webpage_content,
)


@server.tool(
    name="ddg_web_search",
    description=(
        "Search the web using DuckDuckGo. Returns clean destination URLs, "
        "titles, and snippets. Supports optional time filtering ('day', 'week', 'month', 'year')."
    ),
)
async def ddg_web_search(
    query: str,
    max_results: int = 10,
    time_range: str | None = None,
) -> str:
    """Executes a DuckDuckGo search query.

    Args:
        query: Search keywords or question.
        max_results: Maximum results to retrieve (default: 10).
        time_range: Optional recency filter ('day', 'week', 'month', 'year').
    """
    results = await duckduckgo_search(query=query, max_results=max_results, time_range=time_range)
    return json.dumps(
        {"query": query, "count": len(results), "results": results}, indent=2, ensure_ascii=False
    )


@server.tool(
    name="ddg_instant_answer",
    description=(
        "Query DuckDuckGo Instant Answer API for quick definitions, entity summaries, "
        "abstracts, and authoritative topic links without parsing full web search results."
    ),
)
async def ddg_instant_answer(query: str) -> str:
    """Gets instant encyclopedic answer for a topic or entity.

    Args:
        query: Entity name, definition target, or question.
    """
    answer = await duckduckgo_instant_answer(query=query)
    return json.dumps(answer, indent=2, ensure_ascii=False)


@server.tool(
    name="ddg_extract_page",
    description=(
        "Extract clean, readable markdown content, documentation, or articles "
        "from a URL using Trafilatura, stripping ads, boilerplate, and navigation."
    ),
)
async def ddg_extract_page(url: str, max_length: int = 8000) -> str:
    """Extracts text content from a target URL.

    Args:
        url: Full web address (e.g. 'https://example.com/docs').
        max_length: Maximum characters to return (default: 8000).
    """
    page_data = await extract_webpage_content(url=url, max_length=max_length)
    return json.dumps(page_data, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    server.run()
