---
name: DeepResearchSkill
description: Specialist technical research skill enforcing SearXNG retrieval, Context7 API resolution, URL liveness checks, and publication-grade research dossier generation.
---

# DeepResearch Skill Guide

> **Purpose**: Provide search engine hierarchy, URL health verification procedures, and dossier generation rules for **DeepResearch**.

---

## Retrieval Precedence Rules

1. **Code & Library Search**: Context7 (`resolve-library-id` -> `query-docs`).
2. **Primary Web Search**: SearXNG (`searxng_web_search`).
3. **Secondary Search**: DuckDuckGo / Exa / Tavily / context.dev.
4. **URL Health Check**: `read_url_content` for zero-hallucination verification.
