#!/usr/bin/env python3
"""MCP server for Perplexity AI Search.

Allows Antigravity, Swarm, and LLM agents to use Perplexity as an MCP tool.
"""

from __future__ import annotations

import json

from mcp.server.mcpserver import MCPServer

from swarm_sdk.search.perplexity import ask_perplexity

# Create the MCP server (mcp 2.x renamed FastMCP to MCPServer)
mcp = MCPServer("perplexity-search")


@mcp.tool(
    name="perplexity_web_search",
    description=(
        "Search the web with Perplexity AI. Returns synthesized factual answers, "
        "cited sources with URLs and snippets, and related follow-up queries."
    ),
)
async def perplexity_web_search(query: str, focus: str = "web") -> str:
    """Search the live web using Perplexity AI.

    Args:
        query: The question or query to search for.
        focus: The focus mode (default: 'web').

    Returns:
        JSON string containing answer, sources, and related queries.
    """
    result = await ask_perplexity(query=query, focus=focus)
    return json.dumps(result, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
