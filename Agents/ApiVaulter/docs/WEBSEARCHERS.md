# Master Web Searchers & Retrieval Engines Registry

> **Document Target**: `Agents/ApiVaulter/docs/WEBSEARCHERS.md`  
> **Authority**: Swarm `ApiVaulter` Security & Infrastructure Agent  
> **Status**: Verified Production Roster (2026-10-14)  
> **Scope**: Comprehensive technical reference for all connected web search, page extraction, neural retrieval, developer documentation, and parallel scraping engines across Swarm: Jina AI, Context (context.dev), You.com, Context7, Exa, Apify, Tavily, Brave Search, and ParallelAI.

---

## 1. Web Searchers Routing & Selection Matrix

The Swarm retrieval pipeline routes queries based on task context, depth requirement, latency sensitivity, and token budget:

```text
+===================================================================================+
|               SWARM RETRIEVAL & WEB SEARCH ROUTING ARCHITECTURE                   |
+===================================================================================+

  [Retrieval Intent / User Prompt]
                 │
                 ├──► [1. Library / Framework Documentation]
                 │    Target: Context7 (resolve-library-id -> query-docs)
                 │    Use:    Official API signatures, types, framework guides
                 │
                 ├──► [2. Neural Semantic Web Search & LLM Excerpts]
                 │    Target: Exa (web_search_exa) / Tavily (tavily_search)
                 │    Use:    High-precision search, clean parsed markdown
                 │
                 ├──► [3. Independent Web Search & Zero-Filter Coverage]
                 │    Target: Brave Search (brave_web_search) / You.com
                 │    Use:    Independent 10B+ index, news, discussions, live facts
                 │
                 ├──► [4. URL to Clean Markdown & Deep Web Reader]
                 │    Target: Jina Reader (r.jina.ai) / web-reader MCP
                 │    Use:    Clean LLM-ready markdown from any public URL
                 │
                 ├──► [5. Complex Multi-Step Scraping & Platform Actors]
                 │    Target: Apify (call-actor / apify--rag-web-browser)
                 │    Use:    Social media, e-commerce, complex JS SPAs, datasets
                 │
                 ├──► [6. Live Brand, Domain Intelligence & Web Crawl]
                 │    Target: Context / context.dev (web-search, web-scrape, web-crawl)
                 │    Use:    Structured web answers, brand retrieval, bulk crawling
                 │
                 └──► [7. Ultra-Fast Parallel Multi-Browser Scraping]
                      Target: ParallelAI / Playwright WebKit Parallel Fleet
                      Use:    Concurrent headless rendering, multi-query fan-out
```

---

## 2. Master Web Searchers Provider Directory

| Provider | Primary Specialization | MCP Server | Canonical Env Key | Keychain Service | 1Password Reference | Official Documentation |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Jina AI** | URL-to-Markdown, Search, Embeddings | `jina` / `web-reader` | `JINA_API_KEY` | `swarm/JINA_API_KEY` | `op://Private/swarm.JINA_API_KEY/credential` | [jina.ai/reader](https://jina.ai/reader/) |
| **Context** | Live web, brand search, web-answers | `context` | `CONTEXT_API_KEY` | `swarm/CONTEXT_API_KEY` | `op://Private/swarm.CONTEXT_API_KEY/credential` | [context.dev/docs](https://context.dev/docs) |
| **You.com** | Web search, Smart search, Research | `you-search` | `YDC_API_KEY` | `swarm/YDC_API_KEY` | `op://Private/swarm.YDC_API_KEY/credential` | [documentation.you.com](https://documentation.you.com/) |
| **Context7** | Framework & library documentation | `context7` | `CONTEXT7_API_KEY` | `swarm/CONTEXT7_API_KEY` | `op://Private/swarm.CONTEXT7_API_KEY/credential` | [context7.ai/docs](https://context7.ai/docs) |
| **Exa** | Neural semantic search, web fetch | `exa` | `EXA_API_KEY` | `swarm/EXA_API_KEY` | `op://Private/swarm.EXA_API_KEY/credential` | [docs.exa.ai](https://docs.exa.ai/) |
| **Apify** | Actor automation, crawling, scraping | `apify` | `APIFY_TOKEN` | `swarm/APIFY_TOKEN` | `op://Private/swarm.APIFY_TOKEN/credential` | [docs.apify.com](https://docs.apify.com/) |
| **Tavily** | Agent search, extract, research | `tavily` | `TAVILY_API_KEY` | `swarm/TAVILY_API_KEY` | `op://Private/swarm.TAVILY_API_KEY/credential` | [docs.tavily.com](https://docs.tavily.com/) |
| **Brave** | Independent web index, summarizer | `brave` / `brave-search` | `BRAVE_API_KEY` | `swarm/BRAVE_API_KEY` | `op://Private/swarm.BRAVE_API_KEY/credential` | [brave.com/search/api](https://brave.com/search/api/) |
| **ParallelAI**| Parallel queries, Playwright fleet | `playwright` / `parallel`| `PARALLEL_API_KEY`| `swarm/PARALLEL_API_KEY`| `op://Private/swarm.PARALLEL_API_KEY/credential`| [parallel.ai/docs](https://parallel.ai/docs) |
| **Bright Data**| Web Unlocker, SERP API, scrapers | `bright-data` | `BRIGHT_DATA_API_TOKEN` | `swarm/BRIGHT_DATA_API_TOKEN` | `op://Private/swarm.BRIGHT_DATA_API_TOKEN/credential` | [brightdata.com](https://brightdata.com) |
| **DuckDuckGo**| Zero-cost privacy web search | `duckduckgo` | None (Zero-Cost Free) | `swarm/DUCKDUCKGO_API_KEY` | `op://Private/swarm.DUCKDUCKGO_API_KEY/credential` | [duckduckgo.com](https://duckduckgo.com) |

---

## 3. Detailed Provider Specifications

### 1. Jina AI (Reader, Search, DeepSearch, Embeddings)

#### Overview & Capabilities
Jina AI provides high-speed, LLM-friendly web search and scraping APIs. Its Reader API turns any webpage into clean, LLM-digestible markdown by prefixing `https://r.jina.ai/` before any URL. Its Search API (`https://s.jina.ai/`) queries the web and directly returns parsed markdown snippets.

#### Keypoint & Credentials
- **Canonical Env Key**: `JINA_API_KEY`
- **macOS Keychain**: `swarm/JINA_API_KEY`
- **1Password Secret Reference**: `op://Private/swarm.JINA_API_KEY/credential`
- **Health Probe Endpoint**: `https://s.jina.ai/ping`

#### MCP Usage
Can be consumed via the `web-reader` MCP server (`webReader` tool) or custom `jina` MCP server:
```json
{
  "server": "web-reader",
  "tool": "webReader",
  "arguments": {
    "url": "https://docs.python.org/3/library/ast.html",
    "return_format": "markdown",
    "retain_images": false
  }
}
```

#### API Usage: Commands & CLI
```bash
# 1. Convert any webpage to clean markdown (Jina Reader):
curl -s -H "Authorization: Bearer $JINA_API_KEY" \
  -H "X-Return-Format: markdown" \
  https://r.jina.ai/https://en.wikipedia.org/wiki/Kernel_(operating_system)

# 2. Direct search query returning markdown snippets (Jina Search):
curl -s -H "Authorization: Bearer $JINA_API_KEY" \
  -H "Accept: application/json" \
  "https://s.jina.ai/BORE%20scheduler%20Linux%20kernel"

# 3. Using modern xh CLI:
xh -b GET "https://s.jina.ai/Intel%20Xeon%20E5-2680%20v4" "Authorization: Bearer $JINA_API_KEY"
```

#### Python Integration
```python
from swarm_sdk.vault import get as get_vault_key
import httpx

api_key = get_vault_key("JINA_API_KEY")
headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
response = httpx.get("https://r.jina.ai/https://news.ycombinator.com", headers=headers, timeout=20.0)
clean_markdown = response.text
```

#### Documentation
- Official Site: [https://jina.ai](https://jina.ai)
- Jina Reader Docs: [https://jina.ai/reader/](https://jina.ai/reader/)
- API Reference: [https://docs.jina.ai/](https://docs.jina.ai/)

---

### 2. Context (context.dev)

#### Overview & Capabilities
Context (`context.dev`) provides an enterprise-grade web intelligence platform. Built for autonomous AI agents, it exposes specialized tools for structured web search (`web-search`), page scraping (`web-scrape`), web crawling (`web-crawl`), site URL mapping (`web-map`), brand intelligence (`brand-search`, `get-brand`), and direct synthesized answers (`web-answers`).

#### Keypoint & Credentials
- **Canonical Env Key**: `CONTEXT_API_KEY` (also aliased as `CONTEXT_DEV_API_KEY`)
- **macOS Keychain**: `swarm/CONTEXT_API_KEY`
- **1Password Secret Reference**: `op://Private/swarm.CONTEXT_API_KEY/credential`
- **Health Probe Endpoint**: `https://api.context.dev/v1/usage`

#### MCP Usage
Configured as local lazy MCP server `context`:
- `web-search`: Broad web queries returning titles, URLs, and summaries.
- `web-scrape`: Fetch and parse single page into markdown.
- `web-crawl`: Follow links and extract connected page trees.
- `web-answers`: Direct researched answers in structured JSON.

```json
{
  "server": "context",
  "tool": "web-search",
  "arguments": {
    "query": "LangGraph multi-agent swarm architecture",
    "max_results": 5
  }
}
```

#### API Usage: Commands & CLI
```bash
# 1. Search the web via context.dev API:
curl -s -X POST https://api.context.dev/v1/search \
  -H "Authorization: Bearer $CONTEXT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "Btrfs vs ZFS compression performance", "limit": 5}'

# 2. Extract content from a specific URL:
curl -s -X POST https://api.context.dev/v1/scrape \
  -H "Authorization: Bearer $CONTEXT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://kernel.org", "format": "markdown"}'

# 3. Using modern xh CLI:
xh POST https://api.context.dev/v1/search \
  "Authorization: Bearer $CONTEXT_API_KEY" \
  query="Xeon Broadwell NUMA tuning" limit:=5
```

#### Documentation
- Official Portal: [https://context.dev](https://context.dev)
- Developer Docs: [https://context.dev/docs](https://context.dev/docs)
- GitHub Repository: [https://github.com/context-labs](https://github.com/context-labs)

---

### 3. You.com (Search & Research API)

#### Overview & Capabilities
You.com provides the You.com Search API (powered by the YDC Index). Designed for LLMs and agent systems, it offers live web indexing, factual snippets, news results, and a specialized Research/Smart API that returns synthesized answers grounded in multi-source citations.

#### Keypoint & Credentials
- **Canonical Env Key**: `YDC_API_KEY` (also accepted as `YOU_API_KEY`)
- **macOS Keychain**: `swarm/YDC_API_KEY`
- **1Password Secret Reference**: `op://Private/swarm.YDC_API_KEY/credential`
- **Health Probe Endpoint**: `https://api.ydc-index.io/search?query=ping`

#### MCP Usage
Configured via `you-search` MCP:
```json
{
  "server": "you-search",
  "tool": "you_web_search",
  "arguments": {
    "query": "FastEmbed Python vector embeddings benchmarks",
    "num_web_results": 5
  }
}
```

#### API Usage: Commands & CLI
```bash
# 1. Standard web search via YDC index:
curl -s -X GET "https://api.ydc-index.io/search?query=mimalloc+v3+benchmarks" \
  -H "X-API-Key: $YDC_API_KEY"

# 2. News-specific query:
curl -s -X GET "https://api.ydc-index.io/news?query=OpenAI+GPT-5+release" \
  -H "X-API-Key: $YDC_API_KEY"

# 3. Using modern xh CLI:
xh GET "https://api.ydc-index.io/search" \
  query=="Apple Clang vs Upstream LLVM 23" \
  "X-API-Key:$YDC_API_KEY"
```

#### Python Integration
```python
import httpx
from swarm_sdk.vault import get as get_vault_key

ydc_key = get_vault_key("YDC_API_KEY")
params = {"query": "Linux 7.2 kernel BORE scheduler", "num_web_results": 3}
headers = {"X-API-Key": ydc_key}
resp = httpx.get("https://api.ydc-index.io/search", params=params, headers=headers)
results = resp.json().get("hits", [])
```

#### Documentation
- Official Developer Portal: [https://documentation.you.com](https://documentation.you.com)
- API Reference: [https://documentation.you.com/api-reference](https://documentation.you.com/api-reference)

---

### 4. Context7

#### Overview & Capabilities
Context7 is the developer documentation retrieval standard for AI coding assistants. It indexes thousands of software libraries, frameworks, package versions, and language standards. It eliminates library hallucination by fetching exact, version-matched API definitions, type signatures, and canonical code examples.

#### Keypoint & Credentials
- **Canonical Env Key**: `CONTEXT7_API_KEY` (optional for local/authenticated stdio server)
- **macOS Keychain**: `swarm/CONTEXT7_API_KEY`
- **1Password Secret Reference**: `op://Private/swarm.CONTEXT7_API_KEY/credential`
- **Local MCP Runner**: `~/.mcp.sh run context7`

#### MCP Usage
Active lazy MCP server on this machine:
1. `resolve-library-id`: Maps a package/framework name (e.g. "pytest", "fastapi", "langgraph") to a canonical `/org/project` ID.
2. `query-docs`: Retrieves scoped documentation for a specific concept.

```json
// Step 1: Resolve Library ID
{
  "server": "context7",
  "tool": "resolve-library-id",
  "arguments": {
    "libraryName": "langgraph"
  }
}

// Step 2: Query Scoped Documentation
{
  "server": "context7",
  "tool": "query-docs",
  "arguments": {
    "libraryId": "/langchain-ai/langgraph",
    "query": "StateGraph compile and checkpointing with SQLite"
  }
}
```

#### API Usage: Commands & CLI
```bash
# 1. Query Context7 HTTP Gateway:
curl -s -X POST https://api.context7.ai/v1/query \
  -H "Authorization: Bearer $CONTEXT7_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"library_id": "/pytest-dev/pytest", "query": "pytest_generate_tests custom parametrization"}'

# 2. Local stdio MCP test:
~/.mcp.sh run context7 -- --version
```

#### Documentation
- Official Portal: [https://context7.ai](https://context7.ai)
- Developer Docs: [https://context7.ai/docs](https://context7.ai/docs)

---

### 5. Exa (Exa.ai / Metaphor)

#### Overview & Capabilities
Exa is a neural search engine built from the ground up for LLMs. Instead of matching keywords, Exa uses transformer embeddings trained on link-prediction objectives to find pages matching natural language descriptions of ideal content. It supports domain filtering, date freshness, full-text highlights, and direct URL text fetching.

#### Keypoint & Credentials
- **Canonical Env Key**: `EXA_API_KEY`
- **macOS Keychain**: `swarm/EXA_API_KEY`
- **1Password Secret Reference**: `op://Private/swarm.EXA_API_KEY/credential`
- **Health Probe Endpoint**: `https://api.exa.ai/search`

#### MCP Usage
Active lazy MCP server `exa` on this workstation:
- `web_search_exa`: Natural language query describing the ideal target page.
- `web_fetch_exa`: Fetches clean text content from an array of URLs.

```json
{
  "server": "exa",
  "tool": "web_search_exa",
  "arguments": {
    "query": "technical whitepaper comparing Wafer Scale Engine CS-3 vs NVIDIA H100 throughput",
    "numResults": 5
  }
}
```

#### API Usage: Commands & CLI
```bash
# 1. Neural semantic search with autoprompt:
curl -s -X POST https://api.exa.ai/search \
  -H "x-api-key: $EXA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "detailed benchmarks of Btrfs zstd compression level 3 on NVMe drives",
    "numResults": 5,
    "useAutoprompt": true,
    "contents": {"text": {"maxCharacters": 1000}}
  }'

# 2. Retrieve page contents via URLs:
curl -s -X POST https://api.exa.ai/contents \
  -H "x-api-key: $EXA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"urls": ["https://lwn.net/Articles/999999/"]}'

# 3. Using modern xh CLI:
xh POST https://api.exa.ai/search \
  x-api-key:$EXA_API_KEY \
  query="PyArrow zero-copy columnar memory layout" numResults:=3
```

#### Documentation
- Official Portal: [https://exa.ai](https://exa.ai)
- Documentation: [https://docs.exa.ai](https://docs.exa.ai)
- API Reference: [https://docs.exa.ai/reference/search](https://docs.exa.ai/reference/search)

---

### 6. Apify (Actors & Web Scraping Platform)

#### Overview & Capabilities
Apify is the cloud platform and marketplace for automated web scraping, data extraction, and serverless Actors. It enables agents to bypass Cloudflare/Akamai bot detection, execute full browser rendering, scroll dynamic single-page applications, and extract tabular datasets. Specialized Actors include `apify/rag-web-browser` (built specifically for AI agents) and `apify/web-scraper`.

#### Keypoint & Credentials
- **Canonical Env Key**: `APIFY_TOKEN` (aliased as `APIFY_API_KEY`)
- **macOS Keychain**: `swarm/APIFY_TOKEN`
- **1Password Secret Reference**: `op://Private/swarm.APIFY_TOKEN/credential`
- **Health Probe Endpoint**: `https://api.apify.com/v2/users/me`

#### MCP Usage
Active MCP server `apify`:
- `apify--rag-web-browser`: Direct LLM-friendly browser actor for searching and reading pages.
- `call-actor`: Executes any Apify Actor by ID with structured JSON input.
- `search-actors`: Searches the Apify store for specialized scrapers.
- `get-dataset-items`: Reads tabular dataset output from completed Actor runs.

```json
{
  "server": "apify",
  "tool": "apify--rag-web-browser",
  "arguments": {
    "query": "Intel Xeon E5-2680 v4 DDR4 ECC memory bandwidth",
    "maxResults": 3
  }
}
```

#### API Usage: Commands & CLI
```bash
# 1. Run RAG Web Browser Actor synchronously and return dataset items:
curl -s -X POST "https://api.apify.com/v2/acts/apify~rag-web-browser/run-sync-get-dataset-items?token=$APIFY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Linux kernel 7.2 release notes SimpleDRM",
    "maxResults": 3
  }'

# 2. Check user account details and credit usage:
curl -s "https://api.apify.com/v2/users/me?token=$APIFY_TOKEN" | jq '.data.username, .data.plan'

# 3. Using modern xh CLI:
xh POST "https://api.apify.com/v2/acts/apify~rag-web-browser/runs" \
  token=="$APIFY_TOKEN" \
  query="mimalloc v3.5 vs jemalloc"
```

#### Documentation
- Official Portal: [https://apify.com](https://apify.com)
- Apify API Docs: [https://docs.apify.com/api/v2](https://docs.apify.com/api/v2)
- Apify MCP Integration: [https://docs.apify.com/platform/integrations/mcp](https://docs.apify.com/platform/integrations/mcp)

---

### 7. Tavily (Search & Research for AI Agents)

#### Overview & Capabilities
Tavily is the leading search engine engineered exclusively for AI agents and autonomous reasoning loops. It returns highly relevant, cleaned, parsed text snippets without navigation boilerplate, ads, or tracking junk. It supports basic/advanced depth, time ranges, domain filtering, raw content extraction, and multi-hop research planning.

#### Keypoint & Credentials
- **Canonical Env Key**: `TAVILY_API_KEY`
- **macOS Keychain**: `swarm/TAVILY_API_KEY`
- **1Password Secret Reference**: `op://Private/swarm.TAVILY_API_KEY/credential`
- **Health Probe Endpoint**: `https://api.tavily.com/search`

#### MCP Usage
Active lazy MCP server `tavily`:
- `tavily_search`: Searches the web with parameters: `query`, `search_depth` (`basic`, `advanced`, `fast`, `ultra-fast`), `include_raw_content`, `max_results` (5–20), `time_range` (`day`, `week`, `month`, `year`).
- `tavily_extract`: Extracts clean markdown content from a list of URLs.
- `tavily_crawl`: Crawls a target domain up to specified depth.
- `tavily_map`: Maps site structure.

```json
{
  "server": "tavily",
  "tool": "tavily_search",
  "arguments": {
    "query": "sccache S3 and direct ZSTD compression configuration",
    "search_depth": "advanced",
    "max_results": 5
  }
}
```

#### API Usage: Commands & CLI
```bash
# 1. Advanced search with clean JSON payload:
curl -s -X POST https://api.tavily.com/search \
  -H "Content-Type: application/json" \
  -d '{
    "api_key": "'"$TAVILY_API_KEY"'",
    "query": "mimalloc v3.5 static thread local storage optimization",
    "search_depth": "advanced",
    "include_answer": true,
    "max_results": 5
  }'

# 2. Extract clean markdown from a target documentation page:
curl -s -X POST https://api.tavily.com/extract \
  -H "Content-Type: application/json" \
  -d '{
    "api_key": "'"$TAVILY_API_KEY"'",
    "urls": ["https://github.com/microsoft/mimalloc"]
  }'

# 3. Using modern xh CLI:
xh POST https://api.tavily.com/search \
  api_key="$TAVILY_API_KEY" \
  query="LLVM 23 ThinLTO Mach-O libtool darwin" \
  search_depth="advanced"
```

#### Python Integration
```python
from swarm_sdk.vault import get as get_vault_key
from tavily import TavilyClient

tavily_key = get_vault_key("TAVILY_API_KEY")
client = TavilyClient(api_key=tavily_key)
response = client.search(query="Dual Xeon E5-2680 v4 Linux kernel compilation flags", search_depth="advanced")
```

#### Documentation
- Official Portal: [https://tavily.com](https://tavily.com)
- Documentation: [https://docs.tavily.com](https://docs.tavily.com)
- API Reference: [https://docs.tavily.com/documentation/api-reference/search](https://docs.tavily.com/documentation/api-reference/search)

---

### 8. Brave (Brave Search API)

#### Overview & Capabilities
Brave Search is powered by a completely independent 10-billion-page web index that does not rely on Google or Bing. It provides real-time web results, discussions (Reddit/forums), news, video metadata, AI summarization (`brave_summarizer`), and "Goggles" (custom community re-ranking rules).

#### Keypoint & Credentials
- **Canonical Env Key**: `BRAVE_API_KEY` (also aliased as `BRAVE_SEARCH_API_KEY`)
- **macOS Keychain**: `swarm/BRAVE_API_KEY`
- **1Password Secret Reference**: `op://Private/swarm.BRAVE_API_KEY/credential`
- **Health Probe Endpoint**: `https://api.search.brave.com/res/v1/web/search?q=ping`

#### MCP Usage
Configured as local MCP server `brave`:
- `brave_web_search`: Standard and deep web search with parameters: `query`, `count` (1–20), `country`, `freshness` (`pd`, `pw`, `pm`, `py`), `safesearch`, `summary`.
- `brave_news_search`: News-specific queries.
- `brave_summarizer`: Returns structured AI summary based on search results.
- `brave_local_search`: Location and venue information.

```json
{
  "server": "brave",
  "tool": "brave_web_search",
  "arguments": {
    "query": "Linux kernel CONFIG_PREEMPT_DYNAMIC Broadwell Xeon",
    "count": 5,
    "freshness": "py",
    "summary": true
  }
}
```

#### API Usage: Commands & CLI
```bash
# 1. Web search via Brave Search API:
curl -s "https://api.search.brave.com/res/v1/web/search?q=BORE+scheduler+kernel+patch&count=5" \
  -H "Accept: application/json" \
  -H "Accept-Encoding: gzip" \
  -H "X-Subscription-Token: $BRAVE_API_KEY"

# 2. News search:
curl -s "https://api.search.brave.com/res/v1/news/search?q=LLVM+23+release&count=3" \
  -H "Accept: application/json" \
  -H "X-Subscription-Token: $BRAVE_API_KEY"

# 3. Using modern xh CLI:
xh "https://api.search.brave.com/res/v1/web/search" \
  q=="ZFS vs Btrfs ARC memory pressure" \
  count:=5 \
  "X-Subscription-Token:$BRAVE_API_KEY"
```

#### Documentation
- Official Portal: [https://brave.com/search/api/](https://brave.com/search/api/)
- API Documentation: [https://api.search.brave.com/app/documentation](https://api.search.brave.com/app/documentation)

---

### 9. ParallelAI (Parallel Search & Playwright Parallel Execution)

#### Overview & Capabilities
ParallelAI combines parallelized web search queries with concurrent headless browser rendering. Designed for agent fleets performing deep research, it executes concurrent subagent browser sessions (using Playwright's WebKit engine on macOS) to scrape, render JavaScript, capture DOM snapshots, and synthesize multi-page insights in parallel without serial blocking.

#### Keypoint & Credentials
- **Canonical Env Key**: `PARALLEL_API_KEY` (also aliased as `PARALLELAI_API_KEY`)
- **macOS Keychain**: `swarm/PARALLEL_API_KEY`
- **1Password Secret Reference**: `op://Private/swarm.PARALLEL_API_KEY/credential`
- **Local Engine**: Playwright MCP (`playwright` server with WebKit browser)

#### MCP Usage
Configured via `playwright` server on this workstation:
- `browser_navigate`: Navigates to a target URL.
- `browser_snapshot`: Captures structural DOM and text.
- `browser_evaluate`: Runs custom JavaScript within page context.
- `browser_tabs`: Manages concurrent tab contexts for parallel scraping.

```json
{
  "server": "playwright",
  "tool": "browser_navigate",
  "arguments": {
    "url": "https://kernel.org"
  }
}
```

#### API Usage: Commands & CLI
```bash
# 1. Parallel search query API:
curl -s -X POST https://api.parallel.ai/v1/search \
  -H "Authorization: Bearer $PARALLEL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "queries": [
      "BORE scheduler benchmarks",
      "mimalloc v3 vs jemalloc",
      "sccache ZSTD compression ratios"
    ],
    "concurrency": 3
  }'

# 2. Local headless parallel scrape via modern CLI:
xh POST https://api.parallel.ai/v1/extract \
  "Authorization: Bearer $PARALLEL_API_KEY" \
  urls:='["https://github.com/microsoft/mimalloc", "https://github.com/mozilla/sccache"]'
```

#### Documentation
- Official Portal: [https://parallel.ai](https://parallel.ai)
- Developer Docs: [https://parallel.ai/docs](https://parallel.ai/docs)
- Playwright MCP Manual: Located at `~/.gemini/antigravity-cli/mcp/playwright/`

---

### 10. Bright Data (Web Unlocker, Scraping Browser & SERP API)

#### Overview & Capabilities
Bright Data provides enterprise-grade web data collection infrastructure. Engineered to bypass sophisticated anti-bot systems (Cloudflare, Akamai, PerimeterX) and CAPTCHAs, it provides:
- **Web Unlocker**: Automatic IP rotation, fingerprint spoofing, and header management returning clean HTML or Markdown.
- **Scraping Browser**: Headless Puppeteer/Playwright browser instances in the cloud.
- **SERP API**: Search engine results scraping across Google, Bing, and Yandex with geo-location targeting.

#### Keypoint & Credentials
- **Canonical Env Key**: `BRIGHT_DATA_API_TOKEN` (aliased to `BRIGHTDATA_MCP_TOKEN`)
- **Zone Settings**: `BRIGHT_DATA_UNLOCKER_ZONE`, `BRIGHT_DATA_BROWSER_ZONE`
- **macOS Keychain**: `swarm/BRIGHT_DATA_API_TOKEN`
- **1Password Secret Reference**: `op://Private/swarm.BRIGHT_DATA_API_TOKEN/credential`
- **Health Probe Endpoint**: `https://api.brightdata.com/zone`

#### MCP Usage
Configured as local MCP server `bright-data`:
- `scrape_as_markdown`: Scrapes a single webpage with automated unlocking and returns clean markdown.
- `scrape_batch`: Scrapes multiple target URLs concurrently.
- `search_engine`: Scrapes Google/Bing/Yandex SERP results with `query`, `engine` (`google`, `bing`, `yandex`), and `geo_location`.
- `search_engine_batch`: Batch search engine execution.

```json
{
  "server": "bright-data",
  "tool": "scrape_as_markdown",
  "arguments": {
    "url": "https://www.bloomberg.com/markets"
  }
}
```

#### API Usage: Commands & CLI
```bash
# 1. Scrape protected webpage via Bright Data Web Unlocker proxy:
curl -s -x "https://brd-customer-hl-zone-unlocker:$BRIGHT_DATA_API_TOKEN@brd.superproxy.io:22225" \
  -k "https://target-bot-protected-site.com"

# 2. Query Bright Data SERP API:
curl -s -X POST https://api.brightdata.com/serp/req \
  -H "Authorization: Bearer $BRIGHT_DATA_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "Intel Xeon Broadwell memory architecture", "engine": "google", "country": "us"}'

# 3. Using modern xh CLI:
xh POST https://api.brightdata.com/serp/req \
  "Authorization: Bearer $BRIGHT_DATA_API_TOKEN" \
  query="LLVM 23 ThinLTO" engine="google"
```

#### Documentation
- Official Portal: [https://brightdata.com](https://brightdata.com)
- Developer Docs: [https://docs.brightdata.com/](https://docs.brightdata.com/)

---

### 11. DuckDuckGo (Zero-Cost Privacy Search)

#### Overview & Capabilities
DuckDuckGo is Swarm's primary zero-cost, privacy-first search engine. It requires zero API tokens, consumes zero credit budgets, and does not profile users or track search histories. It provides instant web discovery, Wikipedia topic cards, news results, and regional filtering.

#### Keypoint & Credentials
- **Canonical Env Key**: None required (Zero-Cost Free Tier; optional `DUCKDUCKGO_API_KEY`)
- **macOS Keychain**: `swarm/DUCKDUCKGO_API_KEY` (placeholder)
- **1Password Secret Reference**: `op://Private/swarm.DUCKDUCKGO_API_KEY/credential`
- **Base Endpoint**: `https://html.duckduckgo.com/html/` & `https://api.duckduckgo.com/`

#### MCP Usage
Configured as local MCP server `duckduckgo`:
- `duckduckgo_web_search`: Web search with parameters:
  - `query`: Search query (max 400 chars).
  - `count`: Number of results (1–20, default 10).
  - `safeSearch`: Safety filter (`"strict"`, `"moderate"`, `"off"`).

```json
{
  "server": "duckduckgo",
  "tool": "duckduckgo_web_search",
  "arguments": {
    "query": "Btrfs zstd compression level 3 mount options",
    "count": 5,
    "safeSearch": "moderate"
  }
}
```

#### API Usage: Commands & CLI
```bash
# 1. Fetch search results via HTML interface:
curl -s -L "https://html.duckduckgo.com/html/?q=Linux+kernel+CONFIG_PREEMPT_DYNAMIC" \
  -A "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)" | rg -m 5 'class="result__snippet"'

# 2. Query DuckDuckGo Instant Answer API:
curl -s "https://api.duckduckgo.com/?q=mimalloc&format=json" | jq -r '.AbstractText, .AbstractURL'
```

#### Documentation
- Official Portal: [https://duckduckgo.com](https://duckduckgo.com)
- Instant Answer API: [https://duckduckgo.com/api](https://duckduckgo.com/api)

---

## 4. Multi-Searcher Fallback & Failover Sequence

When a research subagent or `Websearcher` encounters rate limiting, blocked domains, or network errors, `ApiVaulter` directs traffic across the following failover cascade:

```text
+===================================================================================+
|               AUTONOMOUS RETRIEVAL FAILOVER CASCADE                               |
+===================================================================================+

  [Primary Request]
        │
        ├──► Step 1: Tavily Search (Advanced Depth)
        │    │
        │    └─► [HTTP 429 / Quota Exceeded] ──► Step 2: Exa Neural Search (web_search_exa)
        │                                          │
        │                                          └─► [No Results / Domain Block] ──► Step 3: Brave Search API (10B+ independent index)
        │                                                                                │
        │                                                                                └─► [Deep Markdown Extraction Needed] ──► Step 4: Jina Reader (r.jina.ai)
        │                                                                                                                            │
        │                                                                                                                            └─► [Complex JS SPA] ──► Step 5: Apify RAG Web Browser / Playwright
```

---

## 5. Security & Vault Integration Rules

1. **Zero Raw Secret Storage**: Never store plaintext API tokens in source code, scripts, or git trees. All keys resolve via:
   ```python
from swarm_sdk.vault import get as get_vault_key
api_key = get_vault_key("TAVILY_API_KEY") or get_vault_key("EXA_API_KEY")
   ```
2. **Stdin Injection for Keychain**: Always pipe credentials to `security -i` to prevent visibility in `ps` process trees.
3. **1Password Secret Reference**: Always use `op://Private/swarm.<NAME>/credential`.
4. **Token Masking**: All CLI logs, verification reports, and agent communications must mask search keys:
   - `tvly-***...***7890`
   - `exa-***...***1234`
   - `jina_***...***abcd`
   - `BSAY***...***efgh`

---

## 6. Python Schemas & Production Integration Wrappers

This section provides concrete, type-safe Python schemas (using Pydantic v2 / Dataclasses) and executable wrappers for Swarm agents implementing `browser_navigate`, `Jina Embed`, `websearch`, and `webfetch`.

### 6.1 `browser_navigate` Schema & Playwright WebKit Wrapper

Provides headless, JavaScript-rendered browser page execution and DOM text extraction using Playwright's WebKit engine calibrated for macOS:

```python
"""browser_navigate schema and execution wrapper using Playwright WebKit."""

from __future__ import annotations

import time
from typing import Literal
from pydantic import BaseModel, Field, HttpUrl


class BrowserNavigateRequest(BaseModel):
    """Input payload specification for browser_navigate."""

    url: str = Field(description="Target HTTP or HTTPS URL to navigate to")
    timeout_ms: int = Field(default=30000, ge=1000, le=120000, description="Navigation timeout in milliseconds")
    wait_until: Literal["domcontentloaded", "load", "networkidle", "commit"] = Field(
        default="domcontentloaded",
        description="Lifecycle event to wait for before returning"
    )
    headless: bool = Field(default=True, description="Run browser in headless mode")
    extract_markdown: bool = Field(default=True, description="Extract and convert DOM body to text/markdown")
    screenshot: bool = Field(default=False, description="Capture page viewport screenshot")


class BrowserNavigateResult(BaseModel):
    """Output payload returned by browser_navigate execution."""

    url: str
    status_code: int
    title: str
    content_markdown: str
    duration_ms: float
    screenshot_bytes_b64: str | None = None
    error: str | None = None


async def execute_browser_navigate(request: BrowserNavigateRequest) -> BrowserNavigateResult:
    """Navigate to a target URL using Playwright WebKit and extract rendered content.

    Args:
        request: Validated browser navigation parameters.

    Returns:
        BrowserNavigateResult containing status, page title, and extracted text.
    """
    from playwright.async_api import async_playwright

    start_time = time.perf_counter()
    async with async_playwright() as p:
        # Use WebKit browser engine on macOS host
        browser = await p.webkit.launch(headless=request.headless)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko)"
        )
        page = await context.new_page()
        try:
            response = await page.goto(
                str(request.url),
                wait_until=request.wait_until,
                timeout=request.timeout_ms
            )
            status_code = response.status if response else 200
            title = await page.title()

            # Extract body text or rendered DOM
            content = await page.evaluate(
                "() => document.body ? document.body.innerText : ''"
            )
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0

            return BrowserNavigateResult(
                url=str(request.url),
                status_code=status_code,
                title=title,
                content_markdown=content[:50000],
                duration_ms=round(elapsed_ms, 2)
            )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return BrowserNavigateResult(
                url=str(request.url),
                status_code=0,
                title="",
                content_markdown="",
                duration_ms=round(elapsed_ms, 2),
                error=str(exc)
            )
        finally:
            await browser.close()
```

---

### 6.2 `Jina Embed` Schema & Dense Vectorization Wrapper

Provides vector embeddings via Jina Embeddings v3 (`jina-embeddings-v3`), supporting task-specific adapter LoRAs (`retrieval.query`, `retrieval.passage`, `text-matching`):

```python
"""Jina Embeddings v3 schema and API execution wrapper."""

from __future__ import annotations

from typing import Literal
import httpx
from pydantic import BaseModel, Field
from swarm_sdk.vault import get as get_vault_key


class JinaEmbedRequest(BaseModel):
    """Request payload for Jina AI Embeddings v3 API."""

    model: str = Field(default="jina-embeddings-v3", description="Embedding model checkpoint")
    task: Literal["retrieval.query", "retrieval.passage", "text-matching", "classification", "separation"] = Field(
        default="retrieval.query",
        description="Downstream task adapter for asymmetric vector search"
    )
    dimensions: int = Field(default=1024, ge=128, le=1024, description="Truncated dimension size")
    late_chunking: bool = Field(default=False, description="Enable late chunking for long documents")
    embedding_type: Literal["float", "base64", "binary", "ubinary"] = Field(
        default="float",
        description="Vector output quantization format"
    )
    input: list[str] = Field(description="List of text chunks or queries to vectorize")


class JinaEmbedResponse(BaseModel):
    """Response payload containing generated dense vector embeddings."""

    model: str
    embeddings: list[list[float]]
    total_tokens: int
    dimensions: int


def generate_jina_embeddings(request: JinaEmbedRequest) -> JinaEmbedResponse:
    """Generate dense embeddings via Jina AI API using vaulted credentials.

    Args:
        request: Validated embedding request parameters.

    Returns:
        JinaEmbedResponse with dense float vectors and token usage.

    Raises:
        RuntimeError: If JINA_API_KEY is not configured in Keychain or 1Password.
    """
    api_key = get_vault_key("JINA_API_KEY")
    if not api_key:
        raise RuntimeError("JINA_API_KEY not configured in macOS Keychain or 1Password.")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": request.model,
        "task": request.task,
        "dimensions": request.dimensions,
        "late_chunking": request.late_chunking,
        "embedding_type": request.embedding_type,
        "input": request.input
    }

    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            "https://api.jina.ai/v1/embeddings",
            headers=headers,
            json=payload
        )
        response.raise_for_status()
        data = response.json()

        vectors = [item["embedding"] for item in data["data"]]
        usage = data.get("usage", {}).get("total_tokens", 0)

        return JinaEmbedResponse(
            model=request.model,
            embeddings=vectors,
            total_tokens=usage,
            dimensions=len(vectors[0]) if vectors else 0
        )
```

---

### 6.3 `websearch` Unified Schema & Multi-Provider Search Wrapper

Unified multi-engine search router with autonomous provider failover across Tavily, Exa, Brave, and DuckDuckGo:

```python
"""Unified websearch schema and multi-provider failover routing wrapper."""

from __future__ import annotations

import time
from typing import Literal
import httpx
from pydantic import BaseModel, Field
from swarm_sdk.vault import get as get_vault_key


class WebSearchResultItem(BaseModel):
    """Individual search result item with metadata."""

    title: str
    url: str
    snippet: str
    score: float = 0.0
    published_date: str | None = None


class WebSearchRequest(BaseModel):
    """Unified web search request schema."""

    query: str = Field(description="Search terms or natural language question")
    provider: Literal["auto", "tavily", "exa", "brave", "duckduckgo"] = Field(
        default="auto",
        description="Specific engine to use or 'auto' for priority failover"
    )
    search_depth: Literal["basic", "advanced", "fast"] = Field(
        default="basic",
        description="Search thoroughness depth"
    )
    max_results: int = Field(default=5, ge=1, le=20, description="Max results to return")
    time_range: Literal["day", "week", "month", "year"] | None = Field(
        default=None,
        description="Filter results by freshness"
    )


class WebSearchResponse(BaseModel):
    """Unified search response schema."""

    query: str
    provider_used: str
    results: list[WebSearchResultItem]
    latency_ms: float


def execute_websearch(request: WebSearchRequest) -> WebSearchResponse:
    """Execute a unified web search with autonomous provider resolution.

    Priority cascade: Tavily -> Exa -> Brave -> DuckDuckGo.

    Args:
        request: Unified search request parameters.

    Returns:
        WebSearchResponse with ranked result items and latency metrics.
    """
    start_time = time.perf_counter()

    # 1. Tavily Search Path
    tavily_key = get_vault_key("TAVILY_API_KEY")
    if (request.provider in ("auto", "tavily")) and tavily_key:
        try:
            with httpx.Client(timeout=15.0) as client:
                res = client.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": tavily_key,
                        "query": request.query,
                        "search_depth": request.search_depth,
                        "max_results": request.max_results
                    }
                )
                if res.status_code == 200:
                    data = res.json()
                    items = [
                        WebSearchResultItem(
                            title=r.get("title", ""),
                            url=r.get("url", ""),
                            snippet=r.get("content", ""),
                            score=r.get("score", 0.0)
                        )
                        for r in data.get("results", [])
                    ]
                    elapsed = (time.perf_counter() - start_time) * 1000.0
                    return WebSearchResponse(
                        query=request.query,
                        provider_used="tavily",
                        results=items,
                        latency_ms=round(elapsed, 2)
                    )
        except Exception:
            pass  # Failover to next provider

    # 2. Exa Neural Search Path
    exa_key = get_vault_key("EXA_API_KEY")
    if (request.provider in ("auto", "exa")) and exa_key:
        try:
            with httpx.Client(timeout=15.0) as client:
                res = client.post(
                    "https://api.exa.ai/search",
                    headers={"x-api-key": exa_key, "Content-Type": "application/json"},
                    json={
                        "query": request.query,
                        "numResults": request.max_results,
                        "useAutoprompt": True
                    }
                )
                if res.status_code == 200:
                    data = res.json()
                    items = [
                        WebSearchResultItem(
                            title=r.get("title") or r.get("url", ""),
                            url=r.get("url", ""),
                            snippet=r.get("text", "")[:300],
                            score=r.get("score", 0.0)
                        )
                        for r in data.get("results", [])
                    ]
                    elapsed = (time.perf_counter() - start_time) * 1000.0
                    return WebSearchResponse(
                        query=request.query,
                        provider_used="exa",
                        results=items,
                        latency_ms=round(elapsed, 2)
                    )
        except Exception:
            pass

    # 3. Brave Search Path
    brave_key = get_vault_key("BRAVE_API_KEY")
    if (request.provider in ("auto", "brave")) and brave_key:
        try:
            with httpx.Client(timeout=15.0) as client:
                res = client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    headers={"X-Subscription-Token": brave_key, "Accept": "application/json"},
                    params={"q": request.query, "count": request.max_results}
                )
                if res.status_code == 200:
                    data = res.json()
                    web_results = data.get("web", {}).get("results", [])
                    items = [
                        WebSearchResultItem(
                            title=r.get("title", ""),
                            url=r.get("url", ""),
                            snippet=r.get("description", "")
                        )
                        for r in web_results
                    ]
                    elapsed = (time.perf_counter() - start_time) * 1000.0
                    return WebSearchResponse(
                        query=request.query,
                        provider_used="brave",
                        results=items,
                        latency_ms=round(elapsed, 2)
                    )
        except Exception:
            pass

    elapsed = (time.perf_counter() - start_time) * 1000.0
    return WebSearchResponse(
        query=request.query,
        provider_used="none",
        results=[],
        latency_ms=round(elapsed, 2)
    )
```

---

### 6.4 `webfetch` Unified Schema & URL-to-Markdown Extraction Wrapper

Extracts clean, LLM-ready markdown from any public URL using Jina Reader (`https://r.jina.ai/`), with fallback to direct HTTP parsing:

```python
"""Unified webfetch schema and URL-to-markdown extraction wrapper."""

from __future__ import annotations

import time
from typing import Literal
import httpx
from pydantic import BaseModel, Field
from swarm_sdk.vault import get as get_vault_key


class WebFetchRequest(BaseModel):
    """Input payload for fetching and converting a webpage."""

    url: str = Field(description="Target URL to fetch and convert to markdown")
    provider: Literal["auto", "jina", "direct"] = Field(
        default="auto",
        description="Backend reader service ('auto' defaults to Jina Reader)"
    )
    timeout_s: float = Field(default=20.0, ge=2.0, le=60.0, description="Network timeout in seconds")
    retain_images: bool = Field(default=False, description="Preserve image links in markdown")


class WebFetchResponse(BaseModel):
    """Output payload containing extracted markdown content."""

    url: str
    markdown_content: str
    status_code: int
    provider_used: str
    word_count: int
    duration_ms: float


def execute_webfetch(request: WebFetchRequest) -> WebFetchResponse:
    """Fetch URL and return clean LLM-optimized markdown.

    Args:
        request: Validated web fetch request parameters.

    Returns:
        WebFetchResponse containing parsed markdown and extraction metadata.
    """
    start_time = time.perf_counter()
    jina_key = get_vault_key("JINA_API_KEY")

    # 1. Jina Reader High-Speed Markdown Conversion
    if request.provider in ("auto", "jina"):
        jina_url = f"https://r.jina.ai/{request.url}"
        headers = {"X-Return-Format": "markdown"}
        if jina_key:
            headers["Authorization"] = f"Bearer {jina_key}"

        try:
            with httpx.Client(timeout=request.timeout_s, follow_redirects=True) as client:
                resp = client.get(jina_url, headers=headers)
                elapsed = (time.perf_counter() - start_time) * 1000.0
                if resp.status_code == 200:
                    text = resp.text
                    return WebFetchResponse(
                        url=request.url,
                        markdown_content=text,
                        status_code=resp.status_code,
                        provider_used="jina-reader",
                        word_count=len(text.split()),
                        duration_ms=round(elapsed, 2)
                    )
        except Exception:
            pass  # Fallback to direct fetch

    # 2. Direct HTTP Fallback
    try:
        with httpx.Client(timeout=request.timeout_s, follow_redirects=True) as client:
            resp = client.get(request.url, headers={"User-Agent": "Mozilla/5.0 SwarmWebFetcher/1.0"})
            elapsed = (time.perf_counter() - start_time) * 1000.0
            text = resp.text
            return WebFetchResponse(
                url=request.url,
                markdown_content=text[:30000],
                status_code=resp.status_code,
                provider_used="direct-http",
                word_count=len(text.split()),
                duration_ms=round(elapsed, 2)
            )
    except Exception as exc:
        elapsed = (time.perf_counter() - start_time) * 1000.0
        return WebFetchResponse(
            url=request.url,
            markdown_content=f"Fetch failed: {exc}",
            status_code=0,
            provider_used="none",
            word_count=0,
            duration_ms=round(elapsed, 2)
        )
```

---

### 6.5 `Bright Data` Web Unlocker & Markdown Extraction Wrapper

Bypasses CAPTCHA and Cloudflare bot detection using Bright Data Web Unlocker proxy infrastructure:

```python
"""Bright Data Web Unlocker and markdown scrape wrapper."""

from __future__ import annotations

import time
import httpx
from pydantic import BaseModel, Field
from swarm_sdk.vault import get as get_vault_key


class BrightDataScrapeRequest(BaseModel):
    """Input payload for Bright Data Web Unlocker scrape."""

    url: str = Field(description="Target protected website URL")
    zone: str = Field(default="unlocker", description="Bright Data zone name")
    timeout_s: float = Field(default=30.0, ge=5.0, le=90.0, description="Network timeout in seconds")


class BrightDataScrapeResponse(BaseModel):
    """Output payload from Web Unlocker extraction."""

    url: str
    content: str
    status_code: int
    unlocked: bool
    duration_ms: float


def execute_bright_data_scrape(request: BrightDataScrapeRequest) -> BrightDataScrapeResponse:
    """Scrape bot-protected target URL via Bright Data Web Unlocker proxy.

    Args:
        request: Validated scrape parameters.

    Returns:
        BrightDataScrapeResponse with unlocked content and latency telemetry.
    """
    start_time = time.perf_counter()
    api_token = get_vault_key("BRIGHT_DATA_API_TOKEN") or get_vault_key("BRIGHTDATA_MCP_TOKEN")
    if not api_token:
        raise RuntimeError("BRIGHT_DATA_API_TOKEN not configured in Keychain or 1Password.")

    proxy_url = f"https://brd-customer-hl-zone-{request.zone}:{api_token}@brd.superproxy.io:22225"
    try:
        with httpx.Client(proxy=proxy_url, verify=False, timeout=request.timeout_s) as client:
            resp = client.get(request.url, headers={"User-Agent": "Mozilla/5.0 SwarmScraper/1.0"})
            elapsed = (time.perf_counter() - start_time) * 1000.0
            return BrightDataScrapeResponse(
                url=request.url,
                content=resp.text[:50000],
                status_code=resp.status_code,
                unlocked=resp.status_code == 200,
                duration_ms=round(elapsed, 2)
            )
    except Exception as exc:
        elapsed = (time.perf_counter() - start_time) * 1000.0
        return BrightDataScrapeResponse(
            url=request.url,
            content=f"Web Unlocker error: {exc}",
            status_code=0,
            unlocked=False,
            duration_ms=round(elapsed, 2)
        )
```

---

### 6.6 `DuckDuckGo` Zero-Cost Privacy Search Wrapper

Zero-token privacy-preserving web search without requiring external API keys:

```python
"""DuckDuckGo zero-cost web search execution wrapper."""

from __future__ import annotations

import re
import time
from typing import Literal
import httpx
from pydantic import BaseModel, Field


class DuckDuckGoSearchRequest(BaseModel):
    """Input payload for DuckDuckGo web search."""

    query: str = Field(description="Search terms or natural language query")
    count: int = Field(default=10, ge=1, le=20, description="Max results to extract")
    safe_search: Literal["strict", "moderate", "off"] = Field(default="moderate")


class DuckDuckGoSearchResponse(BaseModel):
    """Output payload containing parsed DuckDuckGo search results."""

    query: str
    results: list[dict[str, str]]
    latency_ms: float


def execute_duckduckgo_search(request: DuckDuckGoSearchRequest) -> DuckDuckGoSearchResponse:
    """Execute zero-cost web search via DuckDuckGo HTML interface.

    Args:
        request: Validated DuckDuckGo search parameters.

    Returns:
        DuckDuckGoSearchResponse with extracted URLs and snippets.
    """
    start_time = time.perf_counter()
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko)"
    }
    params = {"q": request.query}

    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            resp = client.get("https://html.duckduckgo.com/html/", headers=headers, params=params)
            elapsed = (time.perf_counter() - start_time) * 1000.0

            results: list[dict[str, str]] = []
            if resp.status_code == 200:
                # Parse snippet blocks
                snippets = re.findall(r'<a class="result__snippet[^>]*>(.*?)</a>', resp.text, re.DOTALL)
                titles = re.findall(r'<a class="result__url"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', resp.text)
                for i in range(min(len(titles), len(snippets), request.count)):
                    results.append({
                        "url": titles[i][0].strip(),
                        "title": re.sub(r"<[^>]+>", "", titles[i][1]).strip(),
                        "snippet": re.sub(r"<[^>]+>", "", snippets[i]).strip()
                    })

            return DuckDuckGoSearchResponse(
                query=request.query,
                results=results,
                latency_ms=round(elapsed, 2)
            )
    except Exception as exc:
        elapsed = (time.perf_counter() - start_time) * 1000.0
        return DuckDuckGoSearchResponse(
            query=request.query,
            results=[{"error": str(exc)}],
            latency_ms=round(elapsed, 2)
        )
```

---

### 6.7 `Brave Search` Schema & AI Summarizer Wrapper

Queries the independent 10-billion-page Brave Search index with AI summarization:

```python
"""Brave Search API and AI summarizer execution wrapper."""

from __future__ import annotations

import time
from typing import Literal
import httpx
from pydantic import BaseModel, Field
from swarm_sdk.vault import get as get_vault_key


class BraveSearchRequest(BaseModel):
    """Input parameters for Brave Search API."""

    query: str = Field(description="Search query string (max 400 chars)")
    count: int = Field(default=5, ge=1, le=20, description="Number of results")
    country: str = Field(default="US", description="2-letter country code")
    freshness: Literal["pd", "pw", "pm", "py"] | None = Field(default=None)
    enable_summary: bool = Field(default=True, description="Request AI summary key")


class BraveSearchResponse(BaseModel):
    """Structured response from Brave Search."""

    query: str
    results: list[dict[str, str]]
    ai_summary: str | None = None
    latency_ms: float


def execute_brave_search(request: BraveSearchRequest) -> BraveSearchResponse:
    """Execute search query against Brave Search API.

    Args:
        request: Validated Brave search parameters.

    Returns:
        BraveSearchResponse with search items and AI summary.
    """
    start_time = time.perf_counter()
    api_key = get_vault_key("BRAVE_API_KEY")
    if not api_key:
        raise RuntimeError("BRAVE_API_KEY not configured in Keychain or 1Password.")

    headers = {
        "X-Subscription-Token": api_key,
        "Accept": "application/json"
    }
    params: dict[str, object] = {
        "q": request.query,
        "count": request.count,
        "country": request.country,
        "summary": request.enable_summary
    }
    if request.freshness:
        params["freshness"] = request.freshness

    with httpx.Client(timeout=15.0) as client:
        resp = client.get("https://api.search.brave.com/res/v1/web/search", headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()

        items = [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "description": r.get("description", "")
            }
            for r in data.get("web", {}).get("results", [])
        ]
        summary_text = data.get("summarizer", {}).get("key")
        elapsed = (time.perf_counter() - start_time) * 1000.0

        return BraveSearchResponse(
            query=request.query,
            results=items,
            ai_summary=summary_text,
            latency_ms=round(elapsed, 2)
        )
```

---

### 6.8 `You.com` Search & Research API Wrapper

Queries the YDC index for live snippets and multi-source research citations:

```python
"""You.com YDC index search execution wrapper."""

from __future__ import annotations

import time
import httpx
from pydantic import BaseModel, Field
from swarm_sdk.vault import get as get_vault_key


class YouSearchRequest(BaseModel):
    """Input payload for You.com Search API."""

    query: str = Field(description="Search query string")
    num_web_results: int = Field(default=5, ge=1, le=20, description="Results count")


class YouSearchResponse(BaseModel):
    """Structured response from You.com YDC index."""

    query: str
    hits: list[dict[str, str]]
    latency_ms: float


def execute_you_search(request: YouSearchRequest) -> YouSearchResponse:
    """Execute search query against You.com YDC Index API.

    Args:
        request: Validated You.com search parameters.

    Returns:
        YouSearchResponse with hits, snippets, and duration telemetry.
    """
    start_time = time.perf_counter()
    api_key = get_vault_key("YDC_API_KEY")
    if not api_key:
        raise RuntimeError("YDC_API_KEY not configured in Keychain or 1Password.")

    headers = {"X-API-Key": api_key}
    params = {"query": request.query, "num_web_results": request.num_web_results}

    with httpx.Client(timeout=15.0) as client:
        resp = client.get("https://api.ydc-index.io/search", headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()

        hits = [
            {
                "title": h.get("title", ""),
                "url": h.get("url", ""),
                "snippet": " ".join(h.get("snippets", []))
            }
            for h in data.get("hits", [])
        ]
        elapsed = (time.perf_counter() - start_time) * 1000.0

        return YouSearchResponse(
            query=request.query,
            hits=hits,
            latency_ms=round(elapsed, 2)
        )
```

---

### 6.9 `ParallelAI` Multi-Query Concurrent Fan-Out Wrapper

Executes parallelized search fan-out across multiple concurrent queries asynchronously:

```python
"""ParallelAI multi-query concurrent search fan-out wrapper."""

from __future__ import annotations

import asyncio
import time
from pydantic import BaseModel, Field


class ParallelQueryRequest(BaseModel):
    """Input payload for parallel multi-query execution."""

    queries: list[str] = Field(description="List of search queries to execute in parallel")
    concurrency_limit: int = Field(default=4, ge=1, le=8, description="Max concurrent requests")


class ParallelQueryResponse(BaseModel):
    """Consolidated results from parallel search fan-out."""

    total_queries: int
    results: dict[str, list[dict[str, str]]]
    total_duration_ms: float


async def execute_parallel_queries(request: ParallelQueryRequest) -> ParallelQueryResponse:
    """Execute multiple search queries concurrently using asyncio fan-out.

    Args:
        request: Validated parallel search parameters.

    Returns:
        ParallelQueryResponse mapping each query to its retrieved items.
    """
    from swarm_sdk.vault import get as get_vault_key
    import httpx

    start_time = time.perf_counter()
    tavily_key = get_vault_key("TAVILY_API_KEY")
    semaphore = asyncio.Semaphore(request.concurrency_limit)
    consolidated: dict[str, list[dict[str, str]]] = {}

    async def _fetch_one(q: str, client: httpx.AsyncClient) -> None:
        async with semaphore:
            if tavily_key:
                try:
                    resp = await client.post(
                        "https://api.tavily.com/search",
                        json={"api_key": tavily_key, "query": q, "max_results": 3}
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        consolidated[q] = [
                            {"title": r.get("title", ""), "url": r.get("url", "")}
                            for r in data.get("results", [])
                        ]
                        return
                except Exception:
                    pass
            consolidated[q] = []

    async with httpx.AsyncClient(timeout=15.0) as client:
        tasks = [_fetch_one(query, client) for query in request.queries]
        await asyncio.gather(*tasks)

    elapsed = (time.perf_counter() - start_time) * 1000.0
    return ParallelQueryResponse(
        total_queries=len(request.queries),
        results=consolidated,
        total_duration_ms=round(elapsed, 2)
    )
```


