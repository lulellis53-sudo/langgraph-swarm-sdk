# TechNews pipeline — design

Date: 2026-10-07 | Status: draft, awaiting review | Branch: feat/botdeal

## Amendments (2026-10-07, from planning)

- Location is a standalone top-level `TechNews/` uv project (package `technews`), not `src/technews/`:
  root `uv run` cannot resolve here (`onnxruntime-openvino` has no cp314 wheel).
- No separate `github.py`: GitHub `releases.atom` feeds go through the feed collector.
- `jinja2` is added in stage 5, not stage 1.
- Stage plans: `docs/superpowers/plans/2026-10-07-technews-stage1-scrape-store.md` (stage 1 only).

## Goal

A public TechNews site that republishes short summaries with attribution and links
back. One pipeline feeds it: **websearch/scrape → store → predict → newsletter →
humanize → static site**. Each stage is its own module, built and reviewed in that order.

## Scope of sources (user-specified)

| Category | What is collected | Mechanism |
| --- | --- | --- |
| Big Tech (30 companies) | Company newsroom / engineering blog posts | RSS/Atom first, `site:` web search fallback |
| Git repos | Releases and notable repos | GitHub releases Atom feeds for a watchlist; trending via search fallback |
| Hardware news | CPUs, GPUs, devices, chips | RSS from hardware outlets |
| Code news | Language/tooling/dev-community news | RSS, Hacker News API |
| AI news | Labs, papers, model releases | RSS, arXiv API, lab blogs |

The 30 Big Tech companies (starting list, editable in `sources.yaml`): Apple, Microsoft,
Alphabet/Google, Amazon, Meta, Nvidia, Tesla, Netflix, Oracle, IBM, Intel, AMD,
Qualcomm, Broadcom, Cisco, Salesforce, Adobe, SAP, Samsung, Sony, TSMC, ASML,
OpenAI, Anthropic, Cloudflare, Stripe, GitHub, GitLab, Mozilla, Red Hat.

Feed URLs are **not** hard-coded from memory. `technews sources check` fetches each
declared URL, reports HTTP status and parsed entry count, and flags dead ones; only
sources that pass are enabled. Companies without a working feed use the web-search
fallback (`site:<newsroom domain>`).

## Websearch layer

Reuses `src/swarm_sdk/search/` (DuckDuckGo crawler, keyless) for the fallback and for
`site:`/`intitle:` queries; `httpx` + `selectolax` for fetch/parse (both already in
`pyproject.toml`). New dependencies, each justified: `feedparser` (RSS/Atom
parsing) and `jinja2` (site templates). Checked on PyPI before `uv add`.

Fetcher rules: timeout on every request, honest User-Agent, robots.txt check, per-host
rate limit, retries only on transient errors, no login or paywall bypass.

## Architecture

```
sources.yaml -> scrape -> store (SQLite) -> predict -> newsletter -> humanize -> site/
```

New package `src/technews/` (name `technews`, one module per stage):

- `sources.py` — load/validate `sources.yaml` (category, name, feed or query, enabled).
- `scrape/` — `fetch.py` (guarded HTTP), `feeds.py`, `hn.py`, `github.py`, `search.py`.
- `store.py` — SQLite `articles(id, url, source, category, title, published, excerpt<=300 chars, content_hash, tags)`;
  upsert deduplicated by canonical URL and hash.
- `predict.py` — term-frequency trend series per tag; forecast via adapter to
  `Prediction/engine.py`, with a naive baseline when the engine is unavailable.
- `newsletter.py` — top items + predicted trends → Markdown/HTML digest, written to disk only. Nothing is sent.
- `humanize.py` — `humanize(text, style) -> text`; rule-based prose cleanup of **our own** generated copy
  (strip boilerplate phrases, vary rhythm, enforce style guide). Never rewrites source text; not an AI-detector evasion tool.
- `site.py` + `templates/` — Jinja2: index, per-category pages, per-tag pages, article summary pages, RSS feed, sitemap, meta tags. Output `site/` (gitignored).
- `cli.py` — `technews sources check | scrape | predict | newsletter | build`.

## Content and legal guardrails

Store headline, link, source, date and an excerpt of at most 300 characters. The site
shows our own short summary plus an attribution link to the original. No full-text
republishing. Signup form is a placeholder until a provider is chosen.

## Testing

- Fetcher/parsers against recorded fixture feeds (no live network in tests).
- Store: dedupe, upsert, queries. Predict: deterministic series fixtures.
- Humanizer: table-driven input/output cases. Site: golden-output build test.
- One manual live run (`technews scrape`) reported separately as not part of the suite.
- Gate: the project's quality gate from `AGENTS.md`.

## Build order

1. store + sources + scraper (+ `sources check`) — 2. predict — 3. newsletter —
4. humanizer — 5. site. Each gets review before the next.

## Out of scope

Sending email, deploying/publishing the site, accounts, comments, paywalled content.

## Open items

- Feed URL verification happens at implementation time (`sources check`).
- Package location: new `src/technews/` (recommended) vs reusing the `Newsletter/` worktree.
