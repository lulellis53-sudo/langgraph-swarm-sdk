from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

# Enforce 1 thread for any potential ONNX/Numpy operations under the hood
os.environ["OMP_NUM_THREADS"] = "1"

import importlib
import types


class LazyModule(types.ModuleType):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._module_name = name
        self._loaded_module = None

    def _load(self):
        if self._loaded_module is None:
            self._loaded_module = importlib.import_module(self._module_name)
        return self._loaded_module

    def __getattr__(self, name: str):
        return getattr(self._load(), name)


def lazy_import(name: str):
    return LazyModule(name)


mcpserver = lazy_import("mcp.server.mcpserver")
semantic = lazy_import("WebSearch.scraper.semantic")
llm = lazy_import("WebSearch.scraper.llm")
uvloop = lazy_import("uvloop")
httpx2 = lazy_import("httpx2")
hits_mod = lazy_import("WebSearch.scraper.hits")
agent_tools = lazy_import("WebSearch.scraper.agent_tools")

# Create the MCP server
mcp = mcpserver.MCPServer(
    "WebSearcherMCP", description="High-performance async web scraper and semantic search MCP."
)

# Lazily created pgvector store (one connection per server process)
STORE: Any | None = None


def _store() -> Any:
    global STORE
    if STORE is None:
        STORE = semantic.PgVectorStore()
    return STORE


@mcp.resource("vector_db://status")
async def get_db_status() -> str:
    """Chunks stored in the Postgres/pgvector semantic store, per URL."""
    try:
        stats = await asyncio.to_thread(_store().stats)
    except Exception as e:
        return f"Vector DB unavailable: {type(e).__name__}: {e}"
    if stats.is_empty():
        return "Vector DB is active but empty."
    return (
        f"Vector DB active: {stats['chunks'].sum()} chunks over {stats.height} URLs.\n"
        + "\n".join(f"{u}  {c} chunks  {t}" for u, c, t in stats.iter_rows())
    )


async def _crawl_markdown(url: str) -> str:
    """Fetch ``url`` through Crawl4AI and return its markdown (raises on failure)."""
    req_url = os.environ.get("CRAWL4AI_URL", "http://127.0.0.1:11235") + "/crawl"
    headers = {"Content-Type": "application/json"}
    if token := os.environ.get("CRAWL4AI_API_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    async with httpx2.AsyncClient() as client:
        resp = await client.post(req_url, json={"urls": [url]}, headers=headers, timeout=90.0)
        resp.raise_for_status()
        results = resp.json().get("results") or []
    if not results:
        return ""
    md = results[0].get("markdown", {})
    if isinstance(md, dict):
        return md.get("fit_markdown") or md.get("raw_markdown") or ""
    return md or ""


@mcp.tool()
async def scrape_and_ingest(urls: list[str]) -> str:
    """
    Crawl URLs with Crawl4AI, chunk, embed (FastEmbed int8 MiniLM) and store in pgvector.

    Re-ingesting a URL replaces its previous chunks.

    Args:
        urls: List of web URLs to ingest.
    """
    model = os.environ.get("WEBSCRAPER_EMBED_MODEL") or semantic.DEFAULT_MODEL

    async def one(url: str) -> str:
        try:
            text = await _crawl_markdown(url)
            chunks = await asyncio.to_thread(semantic.chunk_by_tokens, url, text, model)
            if chunks.is_empty():
                return f"{url}: no usable text"
            vectors = await asyncio.to_thread(semantic.embed_texts, chunks["text"].to_list(), model)
            n = await asyncio.to_thread(_store().replace_url, url, chunks, vectors, model)
            total, biggest = chunks["n_tokens"].sum(), chunks["n_tokens"].max()
            return f"{url}: {n} chunks, {total} tokens (largest {biggest})"
        except Exception as e:
            return f"{url}: failed ({type(e).__name__}: {e})"

    results = await asyncio.gather(*(one(u) for u in urls))
    return "Ingested with " + model + ":\n" + "\n".join(results)


async def _semantic_rows(
    query: str, limit: int, url_contains: str | None = None
) -> list[dict[str, Any]]:
    """Top chunks as hit dicts (vector search plus keyword rerank)."""
    model = os.environ.get("WEBSCRAPER_EMBED_MODEL") or semantic.DEFAULT_MODEL
    (vector,) = await asyncio.to_thread(semantic.embed_texts, [query], model)
    found = await asyncio.to_thread(_store().search, vector, model, limit, url_contains)
    if found.is_empty():
        return []
    top = semantic.rerank(found, query, min_similarity=0.12).head(max(limit * 3, 8))
    return [
        hits_mod.from_semantic_chunk(url, idx, text, score)
        for url, idx, text, score in top.select("url", "chunk_idx", "text", "score").iter_rows()
    ]


@mcp.tool()
async def semantic_search(
    query: str,
    limit: int = 5,
    url_contains: str | None = None,
    max_tokens: int = 600,
    min_score: float | None = None,
) -> str:
    """
    Semantic search over ingested pages (vector similarity plus query-term coverage).

    Snippets are pruned to the query and packed into ``max_tokens``.

    Args:
        query: The natural-language query (Portuguese and English both work).
        limit: Max results to return.
        url_contains: Only search URLs containing this text.
        max_tokens: Estimated token budget for the packed brief.
        min_score: Drop chunks whose lexical overlap is below this (0..1).
    """
    try:
        rows = await _semantic_rows(query, limit, url_contains)
    except Exception as e:
        return f"Semantic search failed: {type(e).__name__}: {e}"
    packed = agent_tools.pack_semantic(
        query, rows, limit=limit, max_tokens=max_tokens, min_score=min_score
    )
    return hits_mod.format_brief(packed, len(rows))


async def _searx_results(query: str, limit: int) -> list[dict[str, str]]:
    """Top SearXNG results as ``{"title", "url", "snippet", "source"}`` dicts."""
    base = os.environ.get("SEARXNG_URL", "http://127.0.0.1:8888")
    async with httpx2.AsyncClient() as client:
        resp = await client.get(
            f"{base}/search", params={"format": "json", "q": query}, timeout=10.0
        )
        resp.raise_for_status()
        return hits_mod.from_searxng(resp.json().get("results", [])[:limit])


@mcp.tool()
async def searxng_web_search(
    query: str,
    limit: int = 10,
    max_tokens: int = 400,
    min_score: float | None = None,
) -> str:
    """
    Search the web using the local SearXNG instance.

    Hits are URL-canonicalized, near-duplicates dropped, snippets pruned to the
    query, and packed into ``max_tokens`` so agents spend fewer prompt tokens.

    Args:
        query: The search query string.
        limit: Number of results to return.
        max_tokens: Estimated token budget for the packed brief.
        min_score: Drop hits whose lexical overlap is below this (0..1).
    """
    try:
        results = await _searx_results(query, max(limit * 2, 10))
    except Exception as e:
        return f"SearXNG search failed: {type(e).__name__}: {e}"
    packed = hits_mod.compact_hits(
        results, query, budget_tokens=max_tokens, min_score=min_score, limit=limit
    )
    return hits_mod.format_brief(packed, len(results))


@mcp.tool()
async def crawl4ai_scrape(url: str) -> str:
    """
    Extract high-quality markdown from a URL using the local Crawl4AI instance.

    Args:
        url: The webpage URL to crawl.
    """
    try:
        text = await _crawl_markdown(url)
    except Exception as e:
        return f"Crawl4AI scrape failed: {type(e).__name__}: {e}"
    return text[:20000] if text else "No content."  # truncate to avoid context bloat


def _format_grounded(data: dict[str, Any], limit: int) -> str:
    """Render sources (and answer text, when present) from a Gemini grounded response.

    Handles both shapes: ``candidates[].groundingMetadata`` (generateContent) and
    ``steps[].model_output`` with ``url_citation`` annotations (Interactions).
    """
    rows: list[str] = []
    answer = ""
    meta = (data.get("candidates") or [{}])[0].get("groundingMetadata") or {}
    quoted: dict[int, list[str]] = {}
    for support in meta.get("groundingSupports") or []:
        for i in support.get("groundingChunkIndices") or []:
            quoted.setdefault(i, []).append((support.get("segment") or {}).get("text", ""))
    for i, chunk in enumerate(meta.get("groundingChunks") or []):
        if web := chunk.get("web"):
            snippet = " ".join(quoted.get(i, []))
            rows.append(f"[{web.get('title', '')}]({web.get('uri', '')})\n{snippet}")
    for step in data.get("steps") or []:
        if step.get("type") != "model_output":
            continue
        for part in step.get("content") or []:
            text = part.get("text", "")
            answer += text
            for ann in part.get("annotations") or []:
                if ann.get("type") == "url_citation":
                    quote = text[ann.get("start_index", 0) : ann.get("end_index", 0)]
                    rows.append(f"[{ann.get('title', '')}]({ann.get('url', '')})\n{quote}")
    seen: set[str] = set()
    unique = [r for r in rows if not (r.split("\n", 1)[0] in seen or seen.add(r.split("\n", 1)[0]))]
    if not unique:
        return "No results."
    body = "\n\n".join(unique[:limit])
    return f"{answer}\n\n{body}" if answer else body


@mcp.tool()
async def google_search_agent(
    query: str, limit: int = 10, since: str | None = None, until: str | None = None
) -> str:
    """
    Search Google through Gemini's Google Search grounding (cited sources).

    Needs GOOGLE_API_KEY (optionally GOOGLE_API_KEY_1/_2 as fallbacks) in the environment;
    billing must be enabled on the key. GOOGLE_SEARCH_MODEL overrides the model.

    Args:
        query: The search query string.
        limit: Number of sources to return.
        since: Only results after this RFC 3339 time (e.g. 2026-01-01T00:00:00Z); needs until.
        until: Only results before this RFC 3339 time; needs since.
    """
    if bool(since) != bool(until):
        return "Google search agent: since and until must be given together."
    keys = [
        k
        for n in ("GOOGLE_API_KEY", "GOOGLE_API_KEY_1", "GOOGLE_API_KEY_2")
        if (k := os.environ.get(n))
    ]
    if not keys:
        return "Google search agent not configured: set GOOGLE_API_KEY."
    model = os.environ.get("GOOGLE_SEARCH_MODEL", "gemini-3.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    search_tool: dict[str, Any] = {}
    if since and until:
        search_tool["timeRangeFilter"] = {"startTime": since, "endTime": until}
    body = {"contents": [{"parts": [{"text": query}]}], "tools": [{"google_search": search_tool}]}
    status = None
    try:
        async with httpx2.AsyncClient() as client:
            for key in keys:
                resp = await client.post(
                    url, json=body, headers={"x-goog-api-key": key}, timeout=60.0
                )
                status = resp.status_code
                if status in (401, 403, 429):
                    continue  # rotate to the next key
                resp.raise_for_status()
                break
            else:
                hint = (
                    " (search grounding is not on the free tier: enable billing on the key)"
                    if status == 429
                    else ""
                )
                return f"Google search agent failed: all keys rejected (last HTTP {status}){hint}."
        data = resp.json()
    except Exception as e:
        return f"Google search agent failed: {type(e).__name__}: {e}"
    return _format_grounded(data, limit)


async def _get_status(url: str, headers: dict[str, str] | None = None) -> str:
    """HTTP status of a GET, or the exception name."""
    try:
        async with httpx2.AsyncClient() as client:
            return str((await client.get(url, headers=headers, timeout=8.0)).status_code)
    except Exception as e:
        return type(e).__name__


@mcp.tool()
async def health_check(probe_llm: bool = False) -> str:
    """
    Report the state of every backend (never prints a secret).

    Args:
        probe_llm: Also send a 5-token "hi" with every helper-LLM key (uses a few tokens).
    """
    env = os.environ
    searx = env.get("SEARXNG_URL", "http://127.0.0.1:8888")
    crawl = env.get("CRAWL4AI_URL", "http://127.0.0.1:11235")
    perp = env.get("PERPLEXICA_URL", "http://127.0.0.1:3000")

    async def pg() -> str:
        try:
            stats = await asyncio.to_thread(_store().stats)
        except Exception as e:
            return f"FAIL {type(e).__name__}: {e}"
        chunks = stats["chunks"].sum() if not stats.is_empty() else 0
        return f"ok {chunks} chunks, {stats.height} URLs"

    s_searx, s_crawl, s_perp, s_pg = await asyncio.gather(
        _get_status(f"{searx}/healthz"),
        _get_status(f"{crawl}/health"),
        _get_status(f"{perp}/api/config"),
        pg(),
    )
    google_keys = sum(
        bool(env.get(n)) for n in ("GOOGLE_API_KEY", "GOOGLE_API_KEY_1", "GOOGLE_API_KEY_2")
    )
    perp_cfg = all(
        env.get(n)
        for n in (
            "PERPLEXICA_CHAT_PROVIDER_ID",
            "PERPLEXICA_CHAT_MODEL",
            "PERPLEXICA_EMBED_PROVIDER_ID",
            "PERPLEXICA_EMBED_MODEL",
        )
    )
    token = "set" if env.get("CRAWL4AI_API_TOKEN") else "MISSING"
    xai_key = "set" if env.get("XAI_API_KEY") else "MISSING"
    lines = [
        f"searxng      {'ok' if s_searx == '200' else 'FAIL'} (HTTP {s_searx}) {searx}",
        f"crawl4ai     {'ok' if s_crawl == '200' else 'FAIL'} (HTTP {s_crawl}), token {token}",
        f"pgvector     {s_pg}",
        f"embedding    {env.get('WEBSCRAPER_EMBED_MODEL') or semantic.DEFAULT_MODEL}"
        " (loaded on first use)",
        f"google       {google_keys} key(s) set (not called: search grounding needs billing)",
        f"x_search     XAI_API_KEY {xai_key} (not called: billed per search)",
        f"perplexica   {'ok' if s_perp == '200' else 'FAIL'} (HTTP {s_perp}), "
        f"models {'configured' if perp_cfg else 'NOT configured'}",
    ]
    if probe_llm:
        for label, status, model in await llm.probe():
            lines.append(f"llm {label:14} {status:8} {model}")
    else:
        for prov in llm.PROVIDERS:
            state = "on " if prov.enabled else "off"
            access = (
                f"cli {prov.command[0]} {'found' if prov.available else 'MISSING'}"
                if prov.kind == "cli"
                else f"{len(prov.keys())} key(s)"
            )
            lines.append(
                f"llm {prov.name:14} {state} {access}, "
                f"model {prov.chosen_model()}, effort {prov.effort}, "
                f"maxretry {prov.maxretry}, maxms {prov.maxms}"
            )
    return "\n".join(lines)


@mcp.tool()
async def warmup(include_english_int8: bool = False) -> str:
    """
    Start the embedding models now so the first search or ingest is fast.

    Loads the configured model (downloading it on first use) and its chunking tokenizer,
    then embeds once.

    Args:
        include_english_int8: Also start the English-only int8 MiniLM (all-MiniLM-L6-v2-int8).
    """
    models: list[str | None] = [None]
    if include_english_int8:
        models.append(semantic.ENGLISH_INT8)
    try:
        rows = await asyncio.to_thread(semantic.warmup, models)
    except Exception as e:
        return f"warmup failed: {type(e).__name__}: {e}"
    return "\n".join(
        f"{name}: loaded in {load:.1f}s, then {ms:.0f} ms per embed" for name, load, ms in rows
    )


async def _warm_in_background() -> None:
    """Optional start-up warm-up (WEBSCRAPER_WARMUP=1); errors are logged, never raised."""
    try:
        await asyncio.to_thread(semantic.warmup, [None])
    except Exception as e:
        print(f"warmup failed: {type(e).__name__}: {e}", file=sys.stderr)


def _x_filters(
    handles: list[str] | None,
    exclude_handles: list[str] | None,
    from_date: str | None,
    to_date: str | None,
) -> dict[str, Any]:
    """Validate and build the ``x_search`` tool parameters (raises ValueError on bad input)."""
    import datetime
    import re

    def clean(names: list[str] | None, label: str) -> list[str]:
        out = [n.strip().lstrip("@") for n in names or []]
        if len(out) > 20:
            raise ValueError(f"{label}: at most 20 handles")
        for n in out:
            if not re.fullmatch(r"[A-Za-z0-9_]{1,15}", n):
                raise ValueError(f"{label}: {n!r} is not a valid X handle")
        return out

    tool: dict[str, Any] = {"type": "x_search"}
    if allowed := clean(handles, "handles"):
        tool["allowed_x_handles"] = allowed
    if excluded := clean(exclude_handles, "exclude_handles"):
        tool["excluded_x_handles"] = excluded
    parsed: dict[str, datetime.date] = {}
    for label, value in (("from_date", from_date), ("to_date", to_date)):
        if value:
            try:
                parsed[label] = datetime.date.fromisoformat(value)
            except ValueError as exc:
                raise ValueError(f"{label} must be YYYY-MM-DD, got {value!r}") from exc
            tool[label] = value
    if len(parsed) == 2 and parsed["from_date"] > parsed["to_date"]:
        raise ValueError("from_date is after to_date")
    return tool


def _format_responses(data: dict[str, Any]) -> str:
    """Answer text plus de-duplicated citations from an xAI ``/v1/responses`` reply."""
    text = ""
    cites: list[tuple[str, str]] = []
    for item in data.get("output") or []:
        if item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            text += part.get("text") or ""
            for ann in part.get("annotations") or []:
                if ann.get("url"):
                    cites.append((ann.get("title") or "", ann["url"]))
    text = text or data.get("output_text") or ""
    for c in data.get("citations") or []:
        cites.append(("", c if isinstance(c, str) else c.get("url", "")))
    seen: set[str] = set()
    lines = []
    for title, url in cites:
        if url and url not in seen:
            seen.add(url)
            lines.append(f"- {title + ' ' if title else ''}{url}".replace("  ", " "))
    return text.strip() + ("\n\nCitations:\n" + "\n".join(lines) if lines else "")


@mcp.tool()
async def x_search(
    query: str,
    handles: list[str] | None = None,
    exclude_handles: list[str] | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> str:
    """
    Search X (Twitter) posts with Grok's x_search tool: social-media web search with citations.

    Billed by xAI per search; needs XAI_API_KEY on an account with credits. No other tool calls it.

    Args:
        query: What to look for, in natural language.
        handles: Only consider posts from these handles (max 20, without @).
        exclude_handles: Ignore posts from these handles (max 20, without @).
        from_date: Start of the date range, YYYY-MM-DD.
        to_date: End of the date range, YYYY-MM-DD.
    """
    key = os.environ.get("XAI_API_KEY")
    if not key:
        return "x_search not configured: set XAI_API_KEY (an xAI account with credits)."
    try:
        tool = _x_filters(handles, exclude_handles, from_date, to_date)
    except ValueError as e:
        return f"x_search: {e}"
    body = {
        "model": os.environ.get("XAI_MODEL", "grok-4.7"),
        "input": [{"role": "user", "content": query}],
        "tools": [tool],
    }
    base = os.environ.get("XAI_BASE_URL", "https://api.x.ai/v1").rstrip("/")
    try:
        async with httpx2.AsyncClient() as client:
            resp = await client.post(
                f"{base}/responses",
                json=body,
                headers={"Authorization": f"Bearer {key}"},
                timeout=120.0,
            )
    except Exception as e:
        return f"x_search failed: {type(e).__name__}: {e}"
    if resp.status_code == 403:
        return "x_search failed: HTTP 403. " + resp.text.replace(key, "<key>")[:300]
    if resp.status_code != 200:
        return f"x_search failed: HTTP {resp.status_code} {resp.text.replace(key, '<key>')[:300]}"
    return _format_responses(resp.json()) or "No results."


@mcp.tool()
async def llm_ask(prompt: str, system: str | None = None) -> str:
    """
    Ask a helper LLM (Groq, Novita, Atlas Cloud, OpenRouter free or Gemini, first that answers).

    Args:
        prompt: The question or instruction.
        system: Optional system prompt.
    """
    try:
        text, used = await llm.chat(prompt, system)
    except Exception as e:
        return f"llm_ask failed: {type(e).__name__}: {e}"
    return f"{text}\n\n(model: {used})"


@mcp.tool()
async def ask_with_sources(question: str, limit: int = 5, web: bool = True) -> str:
    """
    Answer a question from the semantic store (and live SearXNG results), citing sources.

    Args:
        question: The question, in any language.
        limit: How many context chunks/results to use.
        web: Also add the top SearXNG results as context.
    """
    raw: list[dict[str, Any]] = []
    try:
        raw.extend(await _semantic_rows(question, limit))
    except Exception:  # store/embedder down: fall back to web context only
        pass
    if web:
        try:
            raw.extend(await _searx_results(question, 6))
        except Exception:
            pass
    if not raw:
        return "No context found (store empty and web search returned nothing)."
    packed = hits_mod.compact_hits(raw, question, budget_tokens=1200, limit=limit + 3)
    context = [(hit["url"], hit["snippet"]) for hit in packed.kept]
    if not context:
        return "No context found (store empty and web search returned nothing)."
    numbered = "\n\n".join(f"[{i}] {src}\n{txt}" for i, (src, txt) in enumerate(context, 1))
    system = (
        "Answer using only the numbered context. Cite sources as [n]. "
        "If the context is insufficient, say so. Reply in the question's language."
    )
    try:
        answer, used = await llm.chat(f"Context:\n{numbered}\n\nQuestion: {question}", system)
    except Exception as e:
        return f"ask_with_sources failed: {type(e).__name__}: {e}"
    refs = "\n".join(f"[{i}] {src}" for i, (src, _) in enumerate(context, 1))
    return f"{answer}\n\nSources:\n{refs}\n(model: {used})"


@mcp.tool()
async def perplexica_search(query: str, focus_mode: str = "webSearch") -> str:
    """
    Ask the local Perplexica (Vane) instance for a cited, LLM-written answer.

    Needs PERPLEXICA_CHAT_PROVIDER_ID / PERPLEXICA_CHAT_MODEL (and the embedding pair)
    naming models configured in Perplexica; the provider must hold a valid API key.

    Args:
        query: The question to answer.
        focus_mode: Perplexica focus mode (webSearch, academicSearch, ...).
    """
    env = os.environ
    chat = {
        "providerId": env.get("PERPLEXICA_CHAT_PROVIDER_ID"),
        "key": env.get("PERPLEXICA_CHAT_MODEL"),
    }
    emb = {
        "providerId": env.get("PERPLEXICA_EMBED_PROVIDER_ID"),
        "key": env.get("PERPLEXICA_EMBED_MODEL"),
    }
    if not all(chat.values()) or not all(emb.values()):
        return (
            "Perplexica not configured: set PERPLEXICA_CHAT_PROVIDER_ID, PERPLEXICA_CHAT_MODEL, "
            "PERPLEXICA_EMBED_PROVIDER_ID and PERPLEXICA_EMBED_MODEL."
        )
    base = env.get("PERPLEXICA_URL", "http://127.0.0.1:3000")
    payload = {
        "chatModel": chat,
        "embeddingModel": emb,
        "optimizationMode": "balanced",
        "focusMode": focus_mode,
        "sources": ["web"],
        "query": query,
        "history": [],
        "stream": False,
    }
    try:
        async with httpx2.AsyncClient() as client:
            resp = await client.post(f"{base}/api/search", json=payload, timeout=120.0)
            resp.raise_for_status()
            body = resp.json()
    except Exception as e:
        return f"Perplexica search failed: {type(e).__name__}: {e}"
    sources = "\n".join(
        f"- {s.get('metadata', {}).get('title', '')} {s.get('metadata', {}).get('url', '')}"
        for s in body.get("sources", [])
    )
    return f"{body.get('message', '')}\n\nSources:\n{sources}"


@mcp.tool()
async def deep_search(query: str, scrape_top: int = 2, use_google: bool = False) -> str:
    """
    Search SearXNG, then scrape the top URLs with Crawl4AI. Google is opt-in (it bills tokens).

    Args:
        query: The search query string.
        scrape_top: How many top distinct URLs to scrape (0 to skip).
        use_google: Also run google_search_agent (Gemini Google Search, billed per search).
    """
    if use_google:
        searx, google = await asyncio.gather(
            searxng_web_search(query, 5), google_search_agent(query, 5)
        )
    else:
        searx, google = await searxng_web_search(query, 5), ""
    urls: list[str] = []
    for block in (searx, google):
        for line in block.splitlines():
            if line.startswith("[") and "](" in line and line.endswith(")"):
                link = line.rsplit("](", 1)[1][:-1]
                if link not in urls:
                    urls.append(link)
    pages = await asyncio.gather(*(crawl4ai_scrape(u) for u in urls[:scrape_top]))
    scraped = "\n\n".join(f"## {u}\n{t[:4000]}" for u, t in zip(urls, pages))
    google_part = f"\n\n# Google\n{google}" if use_google else ""
    return f"# SearXNG\n{searx}{google_part}\n\n# Scraped\n{scraped}"


def main() -> None:
    """Run the WebSearcherMCP server over stdio."""
    # Use uvloop for high performance async operations
    if sys.version_info < (3, 16):  # set_event_loop_policy is deprecated in 3.16
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    if os.environ.get("WEBSCRAPER_WARMUP") == "1":
        import threading

        threading.Thread(target=lambda: asyncio.run(_warm_in_background()), daemon=True).start()
    mcp.run()


if __name__ == "__main__":
    main()
