"""Swarm SDK tool bindings for WebSearch: LangChain tools for agent handoff.

Exposes web search, page fetch, and document deduplication as LangChain
``@tool`` objects compatible with ``model.bind_tools()`` in the Swarm SDK
orchestrator. All tools execute the same core the CLI uses.

Usage from a Swarm SDK worker::

    from WebSearch.swarm_tools import websearch_swarm_tools

    tools = websearch_swarm_tools()
    bound = model.bind_tools(tools)
    # ... invoke via tool_calls / ToolMessage round-trip

Usage with the framework-agnostic layer::

    from WebSearch.swarm_tools import swarm_tool_manifests, swarm_dispatch

    manifests = swarm_tool_manifests()       # OpenAI wire format
    result = swarm_dispatch("web_search", {"query": "..."})
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from WebSearch.agent_tools import search_brief, search_hits
from WebSearch.toolcalling import dispatch_tool_call, tool_manifests

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

__all__ = [
    "SWARM_TOOL_NAMES",
    "swarm_dispatch",
    "swarm_tool_manifests",
    "websearch_swarm_tools",
]

SWARM_TOOL_NAMES = ("web_search", "web_open_page", "web_dedupe")


def websearch_swarm_tools(
    *,
    config: Any | None = None,
    backends: Mapping[str, Callable[[str, Any], list[Any]]] | None = None,
    fetch: Callable[[str], bytes] | None = None,
) -> list[BaseTool]:
    """Return LangChain tools for Swarm SDK agent binding.

    Three tools that map directly to the ``toolcalling.py`` dispatch layer:

    - ``web_search`` — parallel multi-provider search, returns structured hits.
    - ``web_open_page`` — fetch + extract + normalize one URL.
    - ``web_dedupe`` — near-duplicate removal over fetched documents.

    Args:
        config: Provider registry; default ``load_providers()``.
        backends: Searcher id → callable; use in tests to avoid live HTTP.
        fetch: URL → bytes override for ``web_open_page``; default uses httpx.

    Returns:
        List of LangChain ``BaseTool`` objects ready for ``model.bind_tools()``.
    """
    from langchain_core.tools import StructuredTool

    def web_search(query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Search the web across all configured providers in parallel.

        Returns structured hits with title, URL, snippet, and searcher id.
        Google dorks work in the query (site:, after:, before:, -term).
        """
        hits = search_hits(
            query,
            limit=limit,
            config=config,
            backends=backends,
        )
        return [
            {
                "title": hit.title,
                "url": hit.url,
                "snippet": hit.snippet,
                "searcher": hit.searcher_id,
            }
            for hit in hits
        ]

    def web_search_brief(query: str, limit: int = 5, max_chars: int = 1200) -> str:
        """Search the web and return a numbered, token-budgeted brief.

        Cheapest way to answer 'what is out there about X'. Includes titles,
        URLs, and snippets from all configured providers.
        """
        return search_brief(
            query,
            limit=limit,
            max_chars=max_chars,
            config=config,
            backends=backends,
        )

    def web_open_page(url: str, max_chars: int = 4000) -> dict[str, Any]:
        """Fetch one web page and return its main extracted text.

        Boilerplate (menus, footers, ads) is removed. Use after web_search
        when a hit looks promising and the snippet is not enough.
        """
        result = dispatch_tool_call(
            "web_open_page",
            {"url": url, "max_chars": max_chars},
            config=config,
            backends=backends,
            fetch=fetch,
        )
        if "error" in result:
            raise ValueError(result["error"])
        return result

    def web_dedupe(documents: list[dict[str, Any]]) -> dict[str, Any]:
        """Deduplicate fetched documents by near-duplicate fingerprint.

        Returns unique documents plus the dropped duplicates. Use before
        summarizing many pages to avoid wasting tokens on repeats.
        """
        result = dispatch_tool_call(
            "web_dedupe",
            {"documents": documents},
            config=config,
            backends=backends,
            fetch=fetch,
        )
        if "error" in result:
            raise ValueError(result["error"])
        return result

    return [
        StructuredTool.from_function(
            func=web_search,
            name="web_search",
            description=(
                "Search the web across all configured providers in parallel and get "
                "structured hits with titles, URLs, and snippets. Google dorks work "
                "(site:, after:, before:, -term). Cheapest way to answer 'what is "
                "out there about X'."
            ),
        ),
        StructuredTool.from_function(
            func=web_search_brief,
            name="web_search_brief",
            description=(
                "Search the web and return a numbered, token-budgeted brief with "
                "titles, URLs, and snippets. Use when you need a compact overview "
                "rather than structured hits."
            ),
        ),
        StructuredTool.from_function(
            func=web_open_page,
            name="web_open_page",
            description=(
                "Fetch one web page and return its main extracted text (boilerplate "
                "removed). Use after web_search when a hit looks promising and the "
                "snippet is not enough."
            ),
        ),
        StructuredTool.from_function(
            func=web_dedupe,
            name="web_dedupe",
            description=(
                "Deduplicate a list of fetched documents by near-duplicate "
                "fingerprint; returns unique documents plus the dropped duplicates. "
                "Use before summarizing many pages."
            ),
        ),
    ]


def swarm_tool_manifests(*, format: str = "openai") -> list[dict[str, Any]]:
    """Tool definitions in OpenAI or Anthropic wire format.

    Thin alias over ``toolcalling.tool_manifests`` for Swarm SDK callers.
    """
    return tool_manifests(format=format)


def swarm_dispatch(
    name: str,
    arguments: Mapping[str, Any] | str,
    *,
    config: Any | None = None,
    backends: Mapping[str, Callable[[str, Any], list[Any]]] | None = None,
    fetch: Callable[[str], bytes] | None = None,
) -> dict[str, Any]:
    """Execute one tool call and return a JSON-serializable result.

    Thin alias over ``toolcalling.dispatch_tool_call`` for Swarm SDK callers.
    Unknown tools and bad arguments return ``{"error": ...}``.
    """
    return dispatch_tool_call(name, arguments, config=config, backends=backends, fetch=fetch)
