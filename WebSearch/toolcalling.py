"""Framework-agnostic tool-calling layer for the WebSearch agent tool.

Three artifacts, all offline-testable with fake backends:

- ``tool_manifests()`` — JSON-Schema tool definitions in OpenAI (`tools`) and
  Anthropic (`input_schema`) wire formats, ready to paste into any chat-completion
  request or agent SDK config.
- ``dispatch_tool_call()`` — validates a model-emitted ``{"name": ..., "arguments":
  {...}}`` against the manifest and executes it; bad names/arguments return
  structured errors an agent can read and retry, never stack traces.
- ``bind_tools()`` — convenience that returns ``(manifests, dispatch)`` for the
  configured searcher set.

Tools: ``web_search`` (multi-provider search brief), ``web_open_page``
(fetch + extract + normalize one URL), ``web_dedupe`` (simhash dedupe over
fetched documents). Every tool executes the same core the CLI uses; nothing
here shells out or touches the filesystem.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from WebSearch.agent_tools import search_hits

if TYPE_CHECKING:
    from WebSearch.frontend.websearchers import SearchFn

__all__ = [
    "TOOL_NAMES",
    "ToolError",
    "bind_tools",
    "dispatch_tool_call",
    "tool_manifests",
]

TOOL_NAMES = ("web_search", "web_open_page", "web_dedupe")


class ToolError(ValueError):
    """Raised for unknown tool names or malformed arguments (agent-readable)."""


_SEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "minLength": 1,
            "description": "Search query. Google dorks work (site:, after:, before:, -term).",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 20,
            "default": 5,
            "description": "Max hits.",
        },
    },
    "required": ["query"],
}

_OPEN_PAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "pattern": "^https?://",
            "description": "Absolute http(s) page URL.",
        },
        "max_chars": {
            "type": "integer",
            "minimum": 200,
            "maximum": 20000,
            "default": 4000,
            "description": "Extracted-text cap.",
        },
    },
    "required": ["url"],
}

_DEDUPE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "documents": {
            "type": "array",
            "minItems": 1,
            "maxItems": 50,
            "items": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "text": {"type": "string", "minLength": 1},
                },
                "required": ["url", "text"],
            },
            "description": "Fetched pages to deduplicate by near-duplicate fingerprint.",
        },
    },
    "required": ["documents"],
}


def _openai_format(tools: Sequence[tuple[str, str, dict[str, Any]]]) -> list[dict[str, Any]]:
    """Convert one tool list into the OpenAI ``tools`` wire format."""
    return [
        {
            "type": "function",
            "function": {"name": name, "description": description, "parameters": schema},
        }
        for name, description, schema in tools
    ]


def _anthropic_format(tools: Sequence[tuple[str, str, dict[str, Any]]]) -> list[dict[str, Any]]:
    """Convert one tool list into the Anthropic ``input_schema`` wire format."""
    return [
        {"name": name, "description": description, "input_schema": schema}
        for name, description, schema in tools
    ]


def _tools() -> list[tuple[str, str, dict[str, Any]]]:
    """Return the bundled tool declarations consumed by the agent tool backend."""
    return [
        (
            "web_search",
            "Search the web across all configured providers in parallel and get a numbered, "
            "token-budgeted brief with titles, URLs, and snippets. Cheapest way to answer "
            '"what is out there about X".',
            _SEARCH_SCHEMA,
        ),
        (
            "web_open_page",
            "Fetch one web page and return its main extracted text (boilerplate removed). "
            "Use after web_search when a hit looks promising and the snippet is not enough.",
            _OPEN_PAGE_SCHEMA,
        ),
        (
            "web_dedupe",
            "Deduplicate a list of fetched documents by near-duplicate fingerprint; returns "
            "unique documents plus the dropped duplicates. Use before summarizing many pages.",
            _DEDUPE_SCHEMA,
        ),
    ]


def tool_manifests(*, format: str = "openai") -> list[dict[str, Any]]:
    """Tool definitions for chat-completion tool calling.

    Args:
        format: ``"openai"`` (``{"type": "function", "function": {...}}``) or
            ``"anthropic"`` (``{"name", "description", "input_schema"}``).

    Raises:
        ToolError: On an unknown format name.
    """
    if format == "openai":
        return _openai_format(_tools())
    if format == "anthropic":
        return _anthropic_format(_tools())
    raise ToolError(f"unknown manifest format: {format!r} (use 'openai' or 'anthropic')")


def _validate(name: str, arguments: Mapping[str, Any], schema: dict[str, Any]) -> None:
    """Minimal schema validation: required keys, types, bounds the agents break."""
    properties = schema["properties"]
    for key in schema.get("required", ()):
        if key not in arguments:
            raise ToolError(f"{name}: missing required argument {key!r}")
    for key, value in arguments.items():
        spec = properties.get(key)
        if spec is None:
            raise ToolError(f"{name}: unknown argument {key!r}")
        expected = spec.get("type")
        if expected == "string" and not isinstance(value, str):
            raise ToolError(f"{name}: {key!r} must be a string")
        if expected == "integer" and not isinstance(value, int) or isinstance(value, bool):
            raise ToolError(f"{name}: {key!r} must be an integer")
        if expected == "array" and not isinstance(value, list):
            raise ToolError(f"{name}: {key!r} must be an array")
        if "minimum" in spec and isinstance(value, (int, float)) and value < spec["minimum"]:
            raise ToolError(f"{name}: {key!r} must be >= {spec['minimum']}")
        if "maximum" in spec and isinstance(value, (int, float)) and value > spec["maximum"]:
            raise ToolError(f"{name}: {key!r} must be <= {spec['maximum']}")
        if "pattern" in spec and isinstance(value, str):
            import re

            if not re.match(spec["pattern"], value):
                raise ToolError(f"{name}: {key!r} does not match the required pattern")
        if "minLength" in spec and isinstance(value, str) and len(value) < spec["minLength"]:
            raise ToolError(f"{name}: {key!r} is too short")


def _resolve_config(
    config: Any | None, backends: Mapping[str, SearchFn | Callable[[str, Any], list[Any]]] | None
) -> Any:
    """Return ``config``, or one enabling exactly the injected backend ids.

    ``parallel_search(config=None)`` falls back to the global provider registry,
    whose enabled searcher ids never match test backends — so injected backends
    must ship an explicit config or the backend is silently never called.
    """
    if config is not None or not backends:
        return config
    from WebSearch.frontend.websearchers import ProvidersConfig, SearcherSpec

    return ProvidersConfig(
        version=1,
        searchers=tuple(SearcherSpec(id=sid, kind="websearcher", enabled=True) for sid in backends),
        extractor_order=("selectolax",),
    )


def dispatch_tool_call(
    name: str,
    arguments: Mapping[str, Any] | str,
    *,
    config: Any | None = None,
    backends: Mapping[str, SearchFn | Callable[[str, Any], list[Any]]] | None = None,
    fetch: Callable[[str], bytes] | None = None,
) -> dict[str, Any]:
    """Execute one model tool call and return a JSON-serializable result.

    ``arguments`` accepts a mapping or a JSON string (models emit both shapes).
    Unknown tools and bad arguments return ``{"error": ...}`` — an agent can
    read the message and retry; callers never see raw exceptions.
    """
    schemas = {tool[0]: tool[2] for tool in _tools()}
    if name not in schemas:
        return {"error": f"unknown tool {name!r}", "known_tools": list(TOOL_NAMES)}
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments or "{}")
        except json.JSONDecodeError as exc:
            return {"error": f"arguments are not valid JSON: {exc}"}
    if not isinstance(arguments, Mapping):
        return {"error": f"arguments must be an object, got {type(arguments).__name__}"}
    try:
        _validate(name, arguments, schemas[name])
    except ToolError as exc:
        return {"error": str(exc)}

    if name == "web_search":
        hits = search_hits(
            str(arguments["query"]),
            limit=int(arguments.get("limit", 5)),
            config=_resolve_config(config, backends),
            backends=backends,
        )
        return {
            "hits": [
                {
                    "title": hit.title,
                    "url": hit.url,
                    "snippet": hit.snippet,
                    "searcher": hit.searcher_id,
                }
                for hit in hits
            ]
        }

    if name == "web_open_page":
        from WebSearch.backend.docs import extract_and_normalize

        url = str(arguments["url"])
        max_chars = int(arguments.get("max_chars", 4000))
        if fetch is not None:
            raw = fetch(url)
        else:
            import httpx

            host = url.split("/")[2] if "://" in url else ""
            if host.split(":")[0] in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}:
                return {"error": "loopback hosts are not allowed"}
            response = httpx.get(
                url,
                timeout=15.0,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (WebSearch agent tool)"},
            )
            response.raise_for_status()
            raw = response.content
        doc = extract_and_normalize(raw.decode("utf-8", errors="replace"), url)
        return {"url": doc.url, "extractor": doc.extractor, "text": doc.text[:max_chars]}

    # web_dedupe
    from WebSearch.backend.docs import ExtractedDoc, dedupe_docs

    docs = [
        ExtractedDoc(str(d["url"]), str(d["text"]), "agent", max(1, len(str(d["text"])) // 10))
        for d in arguments["documents"]
    ]
    unique = dedupe_docs(docs)
    kept_urls = {doc.url for doc in unique}
    return {
        "unique": [{"url": doc.url, "chars": doc.raw_chars} for doc in unique],
        "dropped": [
            str(d["url"]) for d in arguments["documents"] if str(d["url"]) not in kept_urls
        ],
    }


def bind_tools(
    *,
    config: Any | None = None,
    backends: Mapping[str, SearchFn | Callable[[str, Any], list[Any]]] | None = None,
    fetch: Callable[[str], bytes] | None = None,
    format: str = "openai",
) -> tuple[list[dict[str, Any]], Callable[[str, Mapping[str, Any] | str], dict[str, Any]]]:
    """Return ``(manifests, dispatch)`` for one configured searcher set.

    Example (OpenAI wire format)::

        tools, run_tool = bind_tools(backends=fake_backends)
        response = client.chat.completions.create(model=..., messages=..., tools=tools)
        for call in response.choices[0].message.tool_calls:
            result = run_tool(call.function.name, call.function.arguments)
    """
    return tool_manifests(format=format), lambda name, arguments: dispatch_tool_call(
        name, arguments, config=config, backends=backends, fetch=fetch
    )
