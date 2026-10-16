"""Webengine — the agentic tool belt over the WebSearch pipeline.

One import for agent frameworks::

    from WebSearch.Webengine import Functions, Websearch

    tools = Functions()                      # full LangChain BaseTool belt
    agent = create_agent("openai:gpt-4o-mini", tools=tools)

Single-tool usage — ``Websearch()`` builds one token-budgeted ``websearch``
tool, and the same callable works as a parameterized decorator that attaches
the tool to your agent function::

    research = Websearch(limit=8, max_tokens=600)   # one BaseTool

    @Websearch(limit=5, max_tokens=400)
    def assistant(query: str) -> str: ...
    tools = [assistant.websearch_tool]

Factories for the individual pipeline stages: :func:`WebFetch`,
:func:`Playwright`, :func:`Summarize`, :func:`SemanticSearch`,
:func:`DeepResearch`, :func:`DocFormat`. Shared shapes hang off the
``Websearch`` namespace — ``Websearch.Data.Before``/``.After`` (pipeline
payloads), ``Websearch.FileType`` (accepted document formats), and
``Websearch.Parameters.Firsts``/``.Seconds`` (first-pass search params and
second-pass research params). Injection points (``config``/``backends``/
``fetch``) mirror the underlying modules so tests never touch the network.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
lazy import asyncio
lazy from collections.abc import Callable, Mapping, Sequence
lazy from typing import TYPE_CHECKING, Any, overload

lazy from WebSearch.agents.langchain_tools import websearch_langchain_tools
lazy from WebSearch.agents.swarm_tools import websearch_swarm_tools
lazy from WebSearch.agents.toolcalling import (
    TOOL_NAMES,
    _resolve_config,
    dispatch_tool_call,
    tool_manifests,
)

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from WebSearch.agents.agent_tools import SearchHit
    from WebSearch.backend.docs import ExtractedDoc
    from WebSearch.frontend.websearchers import ProvidersConfig, SearchFn


class WebsearchTool:
    """``websearch`` tool that is also usable as a function decorator.

    ``Websearch(...)`` returns this wrapper: ``invoke``/``ainvoke`` and every
    other attribute delegate to the underlying LangChain ``BaseTool``
    (``.tool`` unwraps it for ``bind_tools``), while calling the wrapper with
    a function (the ``@Websearch(limit=...)`` decorator form) attaches the
    tool as ``func.websearch_tool`` and returns the function unchanged.
    """

    __slots__ = ("_tool",)

    def __init__(self, tool: BaseTool) -> None:
        """Wrap *tool*; decorator calls attach this instance's tool."""
        object.__setattr__(self, "_tool", tool)

    @property
    def tool(self) -> BaseTool:
        """The underlying LangChain ``BaseTool`` (for ``bind_tools``)."""
        return self._tool

    def __call__[**P, T](self, func: Callable[P, T]) -> Callable[P, T]:
        """Decorator form: attach ``.websearch_tool`` and return *func*."""
        func.websearch_tool = self._tool  # type: ignore[attr-defined]
        return func

    def invoke(self, *args: object, **kwargs: object) -> object:
        """Run the tool (delegates to the wrapped BaseTool)."""
        return self._tool.invoke(*args, **kwargs)

    async def ainvoke(self, *args: object, **kwargs: object) -> object:
        """Async tool run (delegates to the wrapped BaseTool)."""
        return await self._tool.ainvoke(*args, **kwargs)

    def __getattr__(self, name: str) -> object:
        """Expose every other BaseTool attribute (name, args, description…)."""
        return getattr(object.__getattribute__(self, "_tool"), name)


class FileType(StrEnum):
    """Document formats understood by the doc-oriented tools."""

    HTML = "html"
    MARKDOWN = "markdown"
    TEXT = "text"
    JSON = "json"
    PDF = "pdf"


class Parameters:
    """Parameter groups shared by the factories."""

    @dataclass(frozen=True, slots=True)
    class Firsts:
        """First-pass search parameters (query → fused hits → brief)."""

        query: str = ""
        limit: int = 5
        max_tokens: int = 400
        min_score: float | None = None

    @dataclass(frozen=True, slots=True)
    class Seconds:
        """Second-pass research parameters (fetch, extract, synthesize)."""

        fetch_limit: int = 3
        max_chars: int = 4000
        research_max_tokens: int = 800


class Data:
    """Payload shapes flowing into and out of the tools."""

    @dataclass(frozen=True, slots=True)
    class Before:
        """What enters the pipeline: the query plus first-pass parameters."""

        query: str
        firsts: Parameters.Firsts = field(default_factory=Parameters.Firsts)

    @dataclass(frozen=True, slots=True)
    class After:
        """What leaves the pipeline: brief, structured hits, token spend."""

        brief: str = ""
        hits: tuple[SearchHit, ...] = ()
        tokens: int = 0

    @dataclass(frozen=True, slots=True)
    class Page:
        """One fetched page after extraction (DeepResearch/DocFormat rows)."""

        url: str
        text: str
        extractor: str = "agent"
        file_type: FileType = FileType.TEXT


def _doc_from(row: Mapping[str, object]) -> ExtractedDoc:
    """Build an ``ExtractedDoc`` from a plain mapping (agent dict shape)."""
    from WebSearch.backend.docs import ExtractedDoc

    text = str(row.get("text") or "")
    return ExtractedDoc(
        url=str(row.get("url") or ""),
        text=text,
        extractor=str(row.get("extractor") or "agent"),
        raw_chars=int(row.get("raw_chars") or len(text)),  # ty: ignore[invalid-argument-type]
    )


def _exclude_providers(
    config: ProvidersConfig | None,
    backends: Mapping[str, SearchFn] | None,
    disable: Sequence[str],
) -> tuple[ProvidersConfig | None, Mapping[str, SearchFn] | None]:
    """Drop *disable*d provider ids from *config* and *backends* (case-insensitive).

    Applied before :func:`_resolve_config` so a synthesized test config never
    re-introduces the disabled ids.
    """
    disabled = {name.strip().lower() for name in disable if name.strip()}
    if not disabled:
        return config, backends
    if backends is not None:
        backends = {key: fn for key, fn in backends.items() if key.lower() not in disabled}
    if config is not None:
        config = replace(
            config, searchers=tuple(s for s in config.searchers if s.id.lower() not in disabled)
        )
    return config, backends


#: Preferred display order of the belt; unknown names are appended by insertion.
_FUNCTION_ORDER = (
    "web_search",
    "web_search_brief",
    "web_search_hits",
    "web_open_page",
    "web_dedupe",
    "web_dedupe_documents",
    "web_summarize_documents",
)


def Functions(
    *,
    config: ProvidersConfig | None = None,
    backends: Mapping[str, SearchFn] | None = None,
    fetch: Callable[[str], bytes] | None = None,
) -> list[BaseTool]:
    """Return the standard WebSearch tool belt for agentic use.

    Args:
        config: Provider registry; default ``load_providers()``.
        backends: Searcher id → callable; inject fakes in tests (no network).
        fetch: URL → bytes override for ``web_open_page``; default uses httpx.

    Returns:
        list[BaseTool]: LangChain tools, de-duplicated by name, in
        :data:`_FUNCTION_ORDER`. When the same name exists in both the
        LangChain and Swarm bindings, the LangChain one wins (it exposes the
        token-budget parameters).
    """
    cfg = _resolve_config(config, backends)
    tools: dict[str, BaseTool] = {
        tool.name: tool for tool in websearch_langchain_tools(config=cfg, backends=backends)
    }
    for tool in websearch_swarm_tools(config=cfg, backends=backends, fetch=fetch):
        tools.setdefault(tool.name, tool)
    ordered = [tools[name] for name in _FUNCTION_ORDER if name in tools]
    ordered.extend(tool for name, tool in tools.items() if name not in _FUNCTION_ORDER)
    return ordered


@overload
def Websearch[**P, T](
    func: Callable[P, T],
    /,
    *,
    config: ProvidersConfig | None = None,
    backends: Mapping[str, SearchFn] | None = None,
    disable: Sequence[str] = (),
    limit: int = 5,
    max_tokens: int = 400,
    min_score: float | None = None,
) -> Callable[P, T]: ...


@overload
def Websearch[**P, T](
    func: None = None,
    /,
    *,
    config: ProvidersConfig | None = None,
    backends: Mapping[str, SearchFn] | None = None,
    disable: Sequence[str] = (),
    limit: int = 5,
    max_tokens: int = 400,
    min_score: float | None = None,
) -> BaseTool: ...


def Websearch[**P, T](
    func: Callable[P, T] | None = None,
    /,
    *,
    config: ProvidersConfig | None = None,
    backends: Mapping[str, SearchFn] | None = None,
    disable: Sequence[str] = (),
    limit: int = 5,
    max_tokens: int = 400,
    min_score: float | None = None,
) -> BaseTool | Callable[P, T]:
    """Build the single ``websearch`` LangChain tool — factory or decorator.

    Called bare (``Websearch()``) or with arguments it returns one
    ``StructuredTool`` named ``websearch``: parallel multi-provider search,
    RRF fusion, dedupe, then a token-budgeted numbered brief. Used as a
    decorator (``@Websearch(limit=8)``) it returns the decorated function
    unchanged and attaches the same tool as ``func.websearch_tool``.

    Args:
        func: Agent function to decorate (bare decorator form).
        config: Provider registry; default synthesized from *backends* when
            those are injected (so tests need no registry entry).
        backends: Searcher id → callable; inject fakes in tests (no network).
        disable: Provider ids to skip **for this search only** (case-insensitive);
            the registry itself is untouched.
        limit: Default max hits in the brief.
        max_tokens: Default tiktoken budget for the rendered brief.
        min_score: Default lexical relevance floor (0..1); ``None`` keeps all.

    Returns:
        BaseTool | Callable: The ``websearch`` tool (factory form) or the
        decorated function carrying ``.websearch_tool`` (decorator form).
    """
    from langchain_core.tools import StructuredTool

    from WebSearch.agents.agent_tools import search_brief

    config, backends = _exclude_providers(config, backends, disable)
    cfg = _resolve_config(config, backends)

    def websearch(
        query: str,
        limit: int = limit,
        max_tokens: int = max_tokens,
        min_score: float | None = min_score,
    ) -> str:
        """Run parallel multi-provider web search; return a numbered brief."""
        return search_brief(
            query,
            limit=limit,
            max_tokens=max_tokens,
            min_score=min_score,
            config=cfg,
            backends=backends,
        )

    tool = StructuredTool.from_function(
        func=websearch,
        name="websearch",
        description=(
            "Search every configured provider in parallel, fuse and dedupe the "
            "hits, and return a numbered brief bounded by a token budget."
        ),
    )
    if func is None:
        return WebsearchTool(tool)
    func.websearch_tool = tool  # type: ignore[attr-defined]
    return func


# Nested namespaces on the Websearch factory: Websearch.Data.Before/.After,
# Websearch.FileType, Websearch.Parameters.Firsts/.Seconds.
Websearch.Data = Data  # type: ignore[attr-defined]
Websearch.FileType = FileType  # type: ignore[attr-defined]
Websearch.Parameters = Parameters  # type: ignore[attr-defined]


def Websearch_DisableProvider(
    *,
    disable: Sequence[str],
    config: ProvidersConfig | None = None,
    backends: Mapping[str, SearchFn] | None = None,
    limit: int = 5,
    max_tokens: int = 400,
    min_score: float | None = None,
) -> BaseTool:
    """``websearch`` tool that skips *disable*d providers for this search only.

    The registry stays untouched — only this tool instance excludes the named
    searcher ids (case-insensitive) from the fan-out. Equivalent to
    ``Websearch(disable=...)`` with ``disable`` required.

    Args:
        disable: Provider ids to exclude (e.g. ``["tavily", "exa"]``).
        config: Provider registry; default synthesized from *backends*.
        backends: Searcher id → callable; inject fakes in tests.
        limit: Default max hits in the brief.
        max_tokens: Default tiktoken budget for the rendered brief.
        min_score: Default lexical relevance floor (0..1); ``None`` keeps all.

    Returns:
        BaseTool: The ``websearch`` tool with the exclusions baked in.
    """
    from typing import cast

    return cast(
        "BaseTool",
        Websearch(
            None,
            config=config,
            backends=backends,
            disable=disable,
            limit=limit,
            max_tokens=max_tokens,
            min_score=min_score,
        ),
    )


async def aWebsearch(
    query: str,
    *,
    config: ProvidersConfig | None = None,
    backends: Mapping[str, SearchFn] | None = None,
    disable: Sequence[str] = (),
    limit: int = 5,
    max_tokens: int = 400,
    min_score: float | None = None,
) -> str:
    """Async one-shot search: run the token-budgeted brief off the event loop.

    Args:
        query: User query (Google dorks work as-is).
        config: Provider registry; default synthesized from *backends*.
        backends: Searcher id → callable; inject fakes in tests.
        disable: Provider ids to skip for this call only.
        limit: Max hits in the brief.
        max_tokens: Tiktoken budget for the rendered brief.
        min_score: Lexical relevance floor (0..1); ``None`` keeps all.

    Returns:
        str: The numbered brief (same contract as the ``websearch`` tool).
    """
    from WebSearch.agents.agent_tools import search_brief

    cfg_backends = backends
    cfg_config, cfg_backends = _exclude_providers(config, cfg_backends, disable)
    cfg = _resolve_config(cfg_config, cfg_backends)
    return await asyncio.to_thread(
        search_brief,
        query,
        limit=limit,
        max_tokens=max_tokens,
        min_score=min_score,
        config=cfg,
        backends=cfg_backends,
    )


def WebFetch(
    *,
    max_chars: int = 4000,
    config: ProvidersConfig | None = None,
    backends: Mapping[str, SearchFn] | None = None,
    fetch: Callable[[str], bytes] | None = None,
) -> BaseTool:
    """Tool: fetch one URL and return extracted, normalized text (httpx by default).

    Args:
        max_chars: Cap on the returned extracted text.
        config: Provider registry (unused by fetch; kept for belt parity).
        backends: Searcher backends (unused by fetch; belt parity).
        fetch: URL → bytes override for tests; default uses httpx.

    Returns:
        BaseTool: ``web_fetch`` — ``(url: str, max_chars: int) -> str``.
    """
    from langchain_core.tools import StructuredTool

    def web_fetch(url: str, max_chars: int = max_chars) -> str:
        """Fetch one page and return its main extracted text."""
        result = dispatch_tool_call(
            "web_open_page",
            {"url": url, "max_chars": max_chars},
            config=config,
            backends=backends,
            fetch=fetch,
        )
        if "error" in result:
            raise ValueError(str(result["error"]))
        return str(result.get("text", ""))

    return StructuredTool.from_function(
        func=web_fetch,
        name="web_fetch",
        description="Fetch one web page and return its main extracted, normalized text.",
    )


def Playwright(
    *,
    timeout_s: float = 20.0,
    max_chars: int = 4000,
) -> BaseTool:
    """Tool: fetch one URL with headless Chromium (Playwright) and extract text.

    Requires the scraping extra (``uv sync --extra scraping`` and
    ``playwright install chromium``); fails closed with ``OSError`` otherwise.

    Returns:
        BaseTool: ``web_browse`` — ``(url: str, max_chars: int) -> str``.
    """
    from langchain_core.tools import StructuredTool

    def web_browse(url: str, max_chars: int = max_chars) -> str:
        """Render one page in headless Chromium and return extracted text."""
        from WebSearch.backend.docs import extract_and_normalize
        from WebSearch.midend.crawlers import fetch_playwright

        raw = fetch_playwright(url, timeout_s=timeout_s)
        doc = extract_and_normalize(raw.decode("utf-8", errors="replace"), url)
        return doc.text[:max_chars]

    return StructuredTool.from_function(
        func=web_browse,
        name="web_browse",
        description=(
            "Open one URL in headless Chromium (handles JS-rendered pages) and "
            "return its extracted text. Slower than web_fetch; use when the "
            "static fetch is empty or blocked."
        ),
    )


def Summarize(*, max_results: int = 10) -> BaseTool:
    """Tool: rank extracted documents semantically and summarize the matches.

    Returns:
        BaseTool: ``web_summarize`` — ``(query, documents) -> dict``.
    """
    from langchain_core.tools import StructuredTool

    from WebSearch.agents.agent_tools import summarize_documents

    def web_summarize(
        query: str, documents: list[dict[str, Any]], max_results: int = max_results
    ) -> dict[str, Any]:
        """Vector-rank documents for the query and return concise summaries."""
        return summarize_documents(
            query, [_doc_from(doc) for doc in documents], max_results=max_results
        )

    return StructuredTool.from_function(
        func=web_summarize,
        name="web_summarize",
        description=(
            "Rank extracted web documents with semantic vector search and return "
            "concise query-relevant summaries."
        ),
    )


def SemanticSearch(*, top_k: int = 10) -> BaseTool:
    """Tool: vector-search provided documents for a query; return ranked results.

    Returns:
        BaseTool: ``web_semantic_search`` — ``(query, documents) -> dict``.
    """
    from langchain_core.tools import StructuredTool

    def web_semantic_search(
        query: str, documents: list[dict[str, Any]], top_k: int = top_k
    ) -> dict[str, Any]:
        """Dedupe/normalize documents, vector-search them, return ranked summaries."""
        from WebSearch.backend.route import dedupe_normalize, semantic_handler

        clean = dedupe_normalize([_doc_from(doc) for doc in documents])
        detail = semantic_handler(query, db_path=":memory:")(clean)
        summaries = list(detail.get("summaries") or [])[:top_k]
        return {"query": query, "count": len(clean), "results": summaries}

    return StructuredTool.from_function(
        func=web_semantic_search,
        name="web_semantic_search",
        description=(
            "Semantic (vector) search over extracted documents: returns the "
            "passages most similar to the query, deduped and normalized first."
        ),
    )


def DeepResearch(
    *,
    firsts: Parameters.Firsts | None = None,
    seconds: Parameters.Seconds | None = None,
    config: ProvidersConfig | None = None,
    backends: Mapping[str, SearchFn] | None = None,
    fetch: Callable[[str], bytes] | None = None,
) -> BaseTool:
    """Tool: search → fetch top pages → dedupe → summarize (two-pass research).

    First pass runs the fused multi-provider search (:data:`Parameters.Firsts`);
    second pass fetches the top pages, normalizes/dedupes them, and produces
    semantic summaries (:data:`Parameters.Seconds`). Fetch failures are skipped
    page-by-page; an empty first pass returns an empty research result.

    Returns:
        BaseTool: ``deep_research`` — ``(query, ...) -> dict`` with brief,
        per-page rows, and summaries.
    """
    from langchain_core.tools import StructuredTool

    firsts = firsts or Parameters.Firsts()
    seconds = seconds or Parameters.Seconds()
    cfg = _resolve_config(config, backends)

    def deep_research(
        query: str,
        limit: int = firsts.limit,
        fetch_limit: int = seconds.fetch_limit,
        max_chars: int = seconds.max_chars,
        max_tokens: int = seconds.research_max_tokens,
    ) -> dict[str, Any]:
        """Search, fetch the best pages, and summarize what was found."""
        from WebSearch.agents.agent_tools import render_brief, search_hits
        from WebSearch.backend.docs import extract_and_normalize
        from WebSearch.backend.route import dedupe_normalize, semantic_handler

        hits = search_hits(query, limit=limit, config=cfg, backends=backends)
        brief = render_brief(list(hits), max_tokens=max_tokens, query=query)
        pages: list[dict[str, Any]] = []
        for hit in hits[:fetch_limit]:
            try:
                if fetch is not None:
                    raw = fetch(hit.url)
                else:
                    from WebSearch.midend.crawl import ordered_fetch

                    raw, _crawler = ordered_fetch(hit.url)
                doc = extract_and_normalize(raw.decode("utf-8", errors="replace"), hit.url)
                pages.append(
                    {"url": doc.url, "text": doc.text[:max_chars], "extractor": doc.extractor}
                )
            except Exception:  # noqa: BLE001 - one dead page must not sink the research
                continue
        clean = dedupe_normalize([_doc_from(page) for page in pages])
        summaries: list[Any] = []
        if clean:
            summaries = list(
                semantic_handler(query, db_path=":memory:")(clean).get("summaries") or []
            )
        return {
            "query": query,
            "brief": brief,
            "pages": [
                {"url": page["url"], "chars": len(page["text"]), "extractor": page["extractor"]}
                for page in pages
            ],
            "summaries": summaries,
        }

    return StructuredTool.from_function(
        func=deep_research,
        name="deep_research",
        description=(
            "Two-pass research: multi-provider search, then fetch and summarize "
            "the best pages. Returns a token-budgeted brief, fetched-page rows, "
            "and semantic summaries."
        ),
    )


def Normalize(
    *,
    model_id: str = "gemini-3.8-flash",
) -> BaseTool:
    """Tool: Gemini-assisted snippet/document normalization (token-saving, fail-open).

    Each document's text is cleaned with ``gemini-3.8-flash`` via the Google
    GenAI API when ``GOOGLE_API_KEY`` is set; without a key or on any failure
    the local ftfy/noise cleaner runs instead, and the model answer is kept
    only when strictly shorter — the pass can never inflate prompt tokens.

    Returns:
        BaseTool: ``web_normalize`` — ``(documents) -> dict`` with cleaned rows.
    """
    from langchain_core.tools import StructuredTool

    def web_normalize(documents: list[dict[str, Any]]) -> dict[str, Any]:
        """Normalize document texts; return cleaned rows plus token savings."""
        from WebSearch.backend.llm_normalize import llm_normalize

        rows: list[dict[str, Any]] = []
        saved = 0
        for row in documents:
            url = str(row.get("url") or "")
            original = str(row.get("text") or "")
            cleaned = llm_normalize(original, model_id=model_id)
            saved += max(0, len(original) - len(cleaned))
            rows.append({"url": url, "text": cleaned, "chars_saved": len(original) - len(cleaned)})
        return {"count": len(rows), "chars_saved": saved, "documents": rows}

    return StructuredTool.from_function(
        func=web_normalize,
        name="web_normalize",
        description=(
            "Clean extracted document texts (mojibake, boilerplate, duplicated "
            "fragments) with Gemini when available — output is never longer, so "
            "prompt tokens only go down."
        ),
    )


def DocFormat(
    *,
    file_type: FileType = FileType.MARKDOWN,
) -> BaseTool:
    """Tool: normalize + dedupe documents and re-emit them in *file_type* format.

    Returns:
        BaseTool: ``doc_format`` — ``(documents) -> dict``.
    """
    from langchain_core.tools import StructuredTool

    def doc_format(documents: list[dict[str, Any]]) -> dict[str, Any]:
        """Normalize, dedupe, and format documents (markdown blocks or JSON rows)."""
        from WebSearch.backend.route import dedupe_normalize

        clean = dedupe_normalize([_doc_from(doc) for doc in documents])
        if file_type is FileType.JSON:
            payload: list[Any] = [asdict(doc) for doc in clean]
        else:
            payload = [f"## {doc.url}\n\n{doc.text}" for doc in clean]
        return {
            "file_type": file_type.value,
            "count": len(clean),
            "removed": len(documents) - len(clean),
            "documents": payload,
        }

    return StructuredTool.from_function(
        func=doc_format,
        name="doc_format",
        description=(
            "Normalize and deduplicate extracted documents, then return them "
            f"formatted as {file_type.value}."
        ),
    )


def manifest(*, format: str = "openai") -> list[dict[str, object]]:
    """Return JSON-schema tool definitions (``format``: ``openai`` or ``anthropic``)."""
    return tool_manifests(format=format)


def dispatch(
    name: str,
    arguments: Mapping[str, object] | str,
    *,
    config: ProvidersConfig | None = None,
    backends: Mapping[str, SearchFn] | None = None,
    fetch: Callable[[str], bytes] | None = None,
) -> dict[str, object]:
    """Execute one model tool call (framework-agnostic; errors are structured)."""
    return dispatch_tool_call(name, arguments, config=config, backends=backends, fetch=fetch)


__all__ = [
    "TOOL_NAMES",
    "Data",
    "DeepResearch",
    "DocFormat",
    "FileType",
    "Functions",
    "Normalize",
    "Parameters",
    "Playwright",
    "SemanticSearch",
    "Summarize",
    "WebFetch",
    "Websearch",
    "Websearch_DisableProvider",
    "aWebsearch",
    "dispatch",
    "manifest",
]
