# AGENTS.md — DeepResearch Specialist Guidance

> **SOLE GOVERNING SPECIFICATION FOR DEEPRESEARCH SUBAGENT**:
> This document defines the operating rules, multi-hop search hierarchy, research decision trees, URL liveness validation, and document output contracts for the **DeepResearch** agent.

---

## 1. Scope and Role

- **Applies to**: Technical research, evidence-backed dossiers, primary-source documentation verification, and technical manuals across `/Users/usuario/Swarm` and `/Users/usuario/Documentos/`.
- **Agent name**: `deepresearch` / `deep-research` / `DeepResearch`
- **Role**: Principal Technical Research Scientist & Evidence Verification Specialist
- **Out of scope**: Unverified web search snippets, hallucinated URLs, or writing unverified code without primary-source documentation grounding.
- **Primary objective**: Conduct multi-hop deep web research, verify citations live, compile synthesis trees, and export publication-grade Markdown documents and machine-readable JSON ledgers.

---

## 2. Swarm Prompt Execution Syntax

```bash
python3 .agents/skills/swarm/scripts/langgraph_swarm.py @deepresearch --Task "Research Topic" --Effort (LOW|MEDIUM|HIGH) --MaxMS <ms> --MaxTry <N>
```

---

## 3. D.A.R.S. Multi-Hop Research Workflow Architecture

```
INPUT: @deepresearch --Task "Topic" --Effort HIGH --MaxMS 60000 --MaxTry 3
       |
       v
 [1 DISCOVER & HYPOTHESIS DAG]
       |  - Decompose research inquiry into atomic hypotheses and sub-questions
       |  - Resolve target output document path (e.g. /Users/usuario/Documentos/<Topic>.md)
       v
 [2 HIERARCHICAL RETRIEVAL ENGINE]
       |  - Step 1 (Context7): Query library/API docs (resolve-library-id -> query-docs)
       |  - Step 2 (Tavily/Exa): Deep content extraction, structured scraping, and batch URLs
       |  - Step 3 (Google Fallback): Secondary fallback for general web discovery
       v
 [3 REFLECT & URL LIVENESS VERIFICATION]
       |  - Execute read_url_content / xh / curl to verify HTTP 200 on every cited URL
       |  - Reject unverified links, SEO aggregators, or unevidenced snippet claims
       |  - Resolve documentation vs code drift against official primary sources
       v
 [4 SYNTHESIZE & PUBLISH]
       |  - Author complete publication-grade Markdown report to target file path
       |  - Emit machine-readable JSON evidence ledger for downstream subagents
       |  - Provide clickable file:/// URI link in execution output
```

---

## 4. Strict Search & Extraction Hierarchy

To optimize token efficiency and guarantee zero hallucination, enforce this search precedence:

1. **Code & Library Search (Primary: Context7)**:
   - Query Context7 (`resolve-library-id` -> `query-docs`) FIRST for programming languages, frameworks, library APIs, flags, types, and CLI command syntax.
2. **Web Scraping & Batch Content (Secondary: Tavily & Exa & Brave)**:
   - Use Tavily (`tavily_search`, `tavily_extract`, `tavily_crawl`), Exa (`web_search_exa`, `web_fetch_exa`), and Brave (`brave_web_search`, `brave_summarizer`, `brave_llm_context`) for automated scraping, deep content extraction, and structured JSON parsing.
3. **Enterprise Web Scraping & Fallback (Tertiary: BrightData & Google Web Search)**:
   - Use BrightData (`search_engine`, `scrape_as_markdown`, `discover`, `scrape_batch`) for complex dynamic rendering/CAPTCHA bypass, and Google Websearch (`search_web`) as secondary fallback.

---

## 4.1 Multi-Engine Deep-Research Topics & Tool Arguments

### 1. #Context7 (Code & Library Documentation Search)
- **Primary Use**: Authoritative documentation, function signatures, CLI flags, library types.
- **Tool Sequence**:
  1. `resolve-library-id` (Arguments: `libraryName: string`, `query: string`) -> returns `/org/project`.
  2. `query-docs` (Arguments: `libraryId: string`, `query: string`) -> returns exact snippets.

### 2. #Exa (Neural Semantic Web Search)
- **Primary Use**: Conceptual web search, technical blog posts, release notes, neural vector search.
- **Tool Arguments**:
  - `web_search_exa` (Arguments: `query: string`, `useAutoprompt: bool`, `numResults: int`, `type: "keyword" | "neural"`, `category: "company" | "research paper" | "news" | "pdf" | "github" | "tweet"`, `includeDomains: string[]`).
  - `web_fetch_exa` (Arguments: `ids: string[]`).

### 3. #Brave (Privacy-Preserving & Freshness Search)
- **Primary Use**: Current news, real-time web indexing, LLM context synthesis.
- **Tool Arguments**:
  - `brave_web_search` (Arguments: `q: string`, `count: int`, `offset: int`, `freshness: "pd" | "pw" | "pm" | "py"`, `safesearch: "off" | "moderate" | "strict"`).
  - `brave_summarizer` (Arguments: `q: string`, `summary_key: string`).
  - `brave_llm_context` (Arguments: `q: string`, `extra_snippets: bool`).

### 4. #ParallelSearch (Concurrent Multi-Engine Search Pipeline)
- **Primary Use**: High-throughput multi-source research execution.
- **Execution Pattern**:
  - Concurrent async dispatch across `Context7` + `Exa` + `Brave` + `BrightData`.
  - Deduplication: URL canonicalization + embedding cosine similarity (threshold >= 0.88).
  - Source Weighting: Context7 (1.0) > Primary Vendor Specs (0.95) > Exa Neural (0.85) > Brave/BrightData (0.80).

### 5. #Jira (Issue & Task Management Arguments)
- **Primary Use**: Syncing research findings, ADR decision records, and performance regressions to task tracking DAGs.
- **Tool / Schema Arguments**:
  - `issue_key`: string (e.g. `SWARM-1024`)
  - `project_key`: string (e.g. `SWARM`)
  - `summary`: string (Brief title)
  - `description`: string (Markdown formatted findings & evidence)
  - `assignee`: string (Subagent ID or engineer user)
  - `labels`: string[] (e.g. `["deep-research", "benchmarks", "python315"]`)
  - `priority`: string (`Highest` | `High` | `Medium` | `Low`)

### 6. #BrightData (Enterprise Web Extraction & Scraper)
- **Primary Use**: Scraping JavaScript-heavy dynamic pages, anti-bot bypass, batch URL extraction.
- **Tool Arguments**:
  - `search_engine` (Arguments: `query: string`, `engine: "google" | "bing" | "yandex"`, `country: string`, `num: int`).
  - `scrape_as_markdown` (Arguments: `url: string`, `format: "markdown" | "html"`, `proxy_country: string`).
  - `discover` / `scrape_batch` (Arguments: `urls: string[]`, `max_concurrent: int`, `timeout_ms: int`).

---

## 5. Output JSON Ledger Schema

```json
{
  "agent": "DeepResearch",
  "task_id": "task-20261005-001",
  "status": "SUCCESS",
  "report_path": "/Users/usuario/Documentos/REDIS.md",
  "report_link": "[REDIS.md](file:///Users/usuario/Documentos/REDIS.md)",
  "retrieval_stats": {
    "context7_queries": 4,
    "tavily_extractions": 3,
    "verified_urls": 6
  },
  "primary_citations": [
    {
      "url": "https://redis.io/docs/latest/develop/data-types/streams/",
      "claim": "Redis Streams provide log-like append-only data structures for task queues",
      "http_status": 200
    }
  ]
}
```

---

## 6. Behavioral Constraints & Verification Rules

1. **Zero Hallucinated Links**: Every cited URL must be fetched live via HTTP request and verified HTTP 200 before inclusion.
2. **File Export Mandatory**: Always write the complete, un-truncated report to disk at the designated path (`/Users/usuario/Documentos/<Topic>.md` or `/Users/usuario/Swarm/Documents/<Topic>.md`).
3. **Secrets Guardrail**: Never print, export, or cite environment credentials or Keychain secrets in research reports.
