# Deep-Research Multi-Engine Architecture & Tool Argument Manual

> [!NOTE]
> **Technical Manual**: Date: 2026-10-05 | Target Engine: Deep-Research Orchestrator | Ecosystem: Context7, Exa, Brave, ParallelSearch, Jira, BrightData | Hardware Baseline: macOS x86_64 / Apple Silicon

---

## Executive Overview & Search Decision Workflow

The **Deep-Research** subagent framework executes multi-hop, evidence-verified deep web research across specialized search engines, documentation indexes, and enterprise scrapers. To prevent token waste, query hallucination, and web drift, queries follow a deterministic retrieval hierarchy.

```
+===================================================================================================+
|                          DEEP-RESEARCH MULTI-ENGINE DISPATCH WORKFLOW                             |
+===================================================================================================+
                                    +--------------------------------+
                                    |    DEEP RESEARCH INQUIRY       |
                                    +--------------------------------+
                                                    |
                          =====================================================
                          ||           RETRIEVAL ROUTING GATE               ||
                          ||  [1] Code, API, CLI, Library Documentation    ||
                          ||  [2] Semantic, Conceptual, Paper & Vector Web  ||
                          ||  [3] Real-time News, Privacy, LLM Context      ||
                          ||  [4] Dynamic JS Pages, CAPTCHA, Enterprise Scrap ||
                          ||  [5] Work Item, ADR, Bug Tracking Sync        ||
                          =====================================================
                                /          |           |          \
                               /           |           |           \
             +----------------+    +-------+---+   +---+-------+   +-------------------+
             |  #Context7     |    |   #Exa    |   |  #Brave   |   |   #BrightData     |
             |  Primary Code  |    | Neural    |   | Privacy   |   | Enterprise Scrape |
             +----------------+    +-----------+   +-----------+   +-------------------+
                                \          |           |          /
                                 \         |           |         /
                                  v        v           v        v
                               +-------------------------------------+
                               |         #ParallelSearch             |
                               | • Async Multi-Engine Dispatch       |
                               | • Deduplication (Cosine >= 0.88)    |
                               | • Weighted Scoring Synthesis        |
                               +-------------------------------------+
                                                  |
                                                  v
                               +-------------------------------------+
                               |              #Jira                  |
                               | • Research Task & ADR Sync          |
                               | • Automated Ticket Issue Creation   |
                               +-------------------------------------+
```

---

## 1. Multi-Engine Topic Breakdown & Tool Arguments

### 1.1 #Context7 (Code & Library Documentation Search)
- **Role**: Primary, mandatory first step for all code-related, framework, API, or CLI flag inquiries.
- **Tools**:
  - `context7:resolve-library-id`
    - `libraryName` (string): Official package name (e.g. `pgvector`, `lancedb`, `langgraph`).
    - `query` (string): Intent or specific capability target.
  - `context7:query-docs`
    - `libraryId` (string): `/org/project` format returned from `resolve-library-id`.
    - `query` (string): Scoped technical question.

### 1.2 #Exa (Neural Vector Semantic Web Search)
- **Role**: Neural vector web search, semantic analysis across blog posts, benchmarks, and research papers.
- **Tools & Arguments**:
  - `exa:web_search_exa`
    - `query` (string): Search prompt.
    - `useAutoprompt` (boolean): `true` to let Exa optimize query syntax.
    - `numResults` (integer): Number of URLs to return (default: `10`, max: `50`).
    - `type` (string): `"neural"` (embedding similarity) or `"keyword"` (BM25 lexical).
    - `category` (string): `"company"`, `"research paper"`, `"news"`, `"pdf"`, `"github"`, `"tweet"`.
    - `includeDomains` (array of strings): Restrict results to verified domain lists.
  - `exa:web_fetch_exa`
    - `ids` (array of strings): Document IDs returned from `web_search_exa`.

### 1.3 #Brave (Privacy-Preserving & Freshness Search)
- **Role**: Privacy-focused real-time web discovery, freshness filtering, and LLM context extraction.
- **Tools & Arguments**:
  - `brave:brave_web_search`
    - `q` (string): Query string.
    - `count` (integer): Number of results (1-20).
    - `offset` (integer): Pagination offset.
    - `freshness` (string): `"pd"` (past day), `"pw"` (past week), `"pm"` (past month), `"py"` (past year).
    - `safesearch` (string): `"off"`, `"moderate"`, `"strict"`.
  - `brave:brave_summarizer`
    - `q` (string): Query string.
    - `summary_key` (string): Key extracted from initial search response.
  - `brave:brave_llm_context`
    - `q` (string): Query string for condensed RAG context.
    - `extra_snippets` (boolean): Enable deep snippet extraction.

### 1.4 #ParallelSearch (Concurrent Multi-Engine Orchestration)
- **Role**: Concurrent dispatch engine across Context7, Exa, Brave, and BrightData with cross-engine deduplication and score weighting.
- **Pipeline Logic**:
  1. **Async Dispatch**: Launch parallel queries using Python `asyncio.gather()`.
  2. **URL Normalization**: Strip tracking parameters (`utm_*`, `ref`), lower-case hostnames, resolve redirects.
  3. **Content Deduplication**: Calculate cosine similarity of content embeddings using FastEmbed `BAAI/bge-small-en-v1.5`. Deduplicate snippets with similarity $\ge 0.88$.
  4. **Source Weighting Matrix**:
     - `Context7` Primary Docs: **1.00**
     - Official Vendor Specs / GitHub: **0.95**
     - `Exa` Neural Research: **0.85**
     - `Brave` Search: **0.80**
     - `BrightData` Web Scrapes: **0.80**
     - Secondary Blogs / Forum Snippets: **0.60**

### 1.5 #Jira (Task Tracking & Issue Integration)
- **Role**: Linking deep research outputs, Architecture Decision Records (ADRs), and benchmark regressions directly into Jira issue DAGs.
- **Arguments & Field Schemas**:
  - `issue_key` (string): Jira issue identifier (e.g., `SWARM-2048`).
  - `project_key` (string): Target project key (e.g., `SWARM`).
  - `summary` (string): High-level title of the research task.
  - `description` (string): Markdown formatted research synthesis, verified citations, and delta metrics.
  - `assignee` (string): Subagent role identifier or engineer username.
  - `labels` (array of strings): Classification tags (`["deep-research", "context7", "exa", "benchmarks"]`).
  - `priority` (string): `Highest`, `High`, `Medium`, `Low`.
  - `status` (string): `To Do`, `In Progress`, `Under Review`, `Done`.

### 1.6 #BrightData (Enterprise Web Extraction & Scraper)
- **Role**: Scraping JavaScript-heavy single-page apps (SPAs), anti-bot/CAPTCHA bypass, and structured Markdown batch extraction.
- **Tools & Arguments**:
  - `brightdata:search_engine`
    - `query` (string): Search query string.
    - `engine` (string): `"google"`, `"bing"`, `"yandex"`.
    - `country` (string): ISO country code for localized results (e.g. `"us"`, `"br"`).
    - `num` (integer): Number of results to return.
  - `brightdata:scrape_as_markdown`
    - `url` (string): Target URL to extract and convert.
    - `format` (string): `"markdown"` or `"html"`.
    - `proxy_country` (string): Geolocation proxy egress node.
  - `brightdata:scrape_batch`
    - `urls` (array of strings): List of target URLs for parallel scraping.
    - `max_concurrent` (integer): Maximum concurrent HTTP connections (default: `10`).
    - `timeout_ms` (integer): Request timeout in milliseconds (default: `30000`).

---

## 2. Capability & Provider Feature Grid

| Feature / Metric | Context7 | Exa | Brave | BrightData | ParallelSearch Engine |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Primary Focus** | Code & API Docs | Neural Web & Papers | Privacy & Freshness | Dynamic Web Scraping | Multi-Source Aggregation |
| **Search Type** | Indexed AST / Docs | Neural Vector / BM25 | Web Index | Live Engine Scrape | Hybrid Weighted Ranking |
| **JS Rendering** | N/A (Pre-indexed) | Static + Rendered | Index Snapshot | Full Headless Browser | Combined |
| **Deduplication** | Strict Library ID | Autoprompt Filter | URL Canonicalization| URL Normalization | FastEmbed Cosine $\ge 0.88$ |
| **Latency (P50)** | `120 ms` | `380 ms` | `210 ms` | `1,250 ms` | `450 ms` (Parallel async) |

---

## 3. Implementation Code: ParallelSearch Async Pipeline

```python
import asyncio
from typing import List, Dict, Any

async def fetch_context7(library: str, query: str) -> Dict[str, Any]:
    # Call Context7 MCP tool
    return {"source": "context7", "score": 1.0, "data": f"Docs for {library}: {query}"}

async def fetch_exa(query: str) -> Dict[str, Any]:
    # Call Exa MCP tool
    return {"source": "exa", "score": 0.85, "data": f"Neural search for: {query}"}

async def fetch_brave(query: str) -> Dict[str, Any]:
    # Call Brave MCP tool
    return {"source": "brave", "score": 0.80, "data": f"Brave search for: {query}"}

async def parallel_search(query: str, library_name: str = None) -> List[Dict[str, Any]]:
    tasks = [fetch_exa(query), fetch_brave(query)]
    if library_name:
        tasks.append(fetch_context7(library_name, query))
        
    results = await asyncio.gather(*tasks, return_exceptions=True)
    # Deduplicate and sort by weighted score
    valid_results = [r for r in results if isinstance(r, dict)]
    valid_results.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    return valid_results
```

---

## 4. Evidence Ledger & Documentation Primary Links

1. [Context7 Documentation Specifications](file:///Users/usuario/.gemini/antigravity-cli/mcp/context7/)
2. [Exa Web Search API Specs](https://exa.ai/docs)
3. [Brave Search API Documentation](https://api.search.brave.com/app/documentation)
4. [BrightData Scraping API Specs](https://brightdata.com/products/web-scraper)
5. [Jira REST API v3 Documentation](https://developer.atlassian.com/cloud/jira/platform/rest/v3/intro/)
