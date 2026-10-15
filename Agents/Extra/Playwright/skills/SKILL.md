---
name: playwright
description: >-
  Sole-owner browser-decision agent for the WebSearch pipeline. Use when a URL
  needs a static-vs-Playwright decision, a headless-Chromium render, hit/text
  critique, or the Groq normalize + summarize passes. Only Websearcher may
  invoke the Playwright tool through this persona.
---

# Playwright skill

Turn a URL or a batch of search hits into clean, critiqued, token-lean text.

## When to use

- A URL's static HTTP fetch returned empty, was JS-rendered, or was blocked, and a headless-Chromium render is needed.
- Search hits or extracted text must be critiqued against a relevance rubric (self-learning).
- The Groq normalize pass (token-saving, fail-open) then the Groq summarize pass must run over extracted text.

## Inputs

| Arg | Type | Default | Notes |
| --- | --- | --- | --- |
| `url` | str | — | Absolute http(s) URL to fetch/render. |
| `query` | str | — | The originating query; drives the critic rubric and the summarize pass. |
| `max_chars` | int | 4000 | Cap on returned extracted/normalized text. |
| `decision` | str | `auto` | `auto` (static→Playwright fallback), `static`, `playwright`, or `skip`. |

## Outputs

`{decision, normalized_text, summary, rubric_update}` — the chosen render path, the cleaned text, the query-relevant summary, and the rubric nudge.

## Ownership

Only `Websearcher` invokes the Playwright tool. Other agents route browsing through `Websearcher`, which delegates here.

## Models

Playwright manager `groq:openai/gpt-oss-120b`; normalize + summarize `groq:openai/gpt-oss-20b`; all fail-open to the local deterministic pipeline without `GROQ_API_KEY`.
