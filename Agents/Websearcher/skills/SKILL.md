---
name: WebsearchAndFetch
description: "Unified web search and content fetching skill for Websearcher. Formulates targeted queries, queries DuckDuckGo/SearXNG/Exa/Tavily, performs headless rendering via Playwright and HTTP extraction via read_url_content, and formats verified primary-source citations."
---

# WebsearchAndFetch Skill: Unified Search & Retrieval Pipeline

> **Authoritative Specification**: Consolidated search query formulation and deterministic page fetching pipeline for `Agents/Websearcher` (incorporating `WebFetch`).
> **Token-Saving Directive**: Adheres strictly to token budgets (`max_prompt: 16384, max_completion: 1024`). Avoids Google Search unless all primary search engines yield zero results.

---

## 1. Capabilities & Task Workflow

The unified `Websearcher` agent operates across three distinct operational modes:
1. **Fact Lookup (`lookup_fact`)**: Rapid targeted search for a single verifiable fact or API signature. Returns a concise answer with verified primary source citations.
2. **Canonical Source Collection (`collect_sources`)**: Discovers, deduplicates, and validates the top primary documentation URLs and RFCs for a technical topic.
3. **Deterministic Page Fetching & Extraction (`fetch_render`)**: Ingests candidate URLs or scratchpad payloads, executes HTTP extraction (`read_url_content`) or Playwright headless browser rendering (`playwright` engine), strips boilerplate/DOM bloat, and returns clean markdown.

---

## 2. Extraction & Retrieval Hierarchy

Following the global research directives:
1. **Context7 (`resolve-library-id` -> `query-docs`)**: Always query Context7 first for library, framework, and API lookups.
2. **DuckDuckGo MCP / Swarm WebSearch**: Primary search engine for general technical queries.
3. **Exa / Tavily / SearXNG**: Secondary deep-crawl engines for structured JSON responses and complex pages.
4. **Playwright Browser Agent**: Concurrent headless rendering for dynamic Single-Page Applications (SPAs) or JavaScript-heavy pages.
5. **Google Web Search (`search_web`)**: Strictly as a last-resort fallback.

---

## 3. Citation & Verification Invariants

1. **Zero Hallucination**: No URL or domain may be cited unless it was actually opened and inspected via `read_url_content` or Playwright.
2. **Primary Source First**: Official repositories, specifications, and vendor docs are preferred over blog posts or scrapers.
3. **Evidence Ledger**: Output answers must map every claim to its exact source URL, section, and access date.
