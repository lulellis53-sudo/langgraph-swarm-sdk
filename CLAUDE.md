# Workspace

`~/Desktop/Workspace` is the folder we manage. Work here, not in `~/Myworkspace`
(archived: `scratch/Myworkspace-2026-10-15.tar.zst`).

## Environment

- Pixi manifest: `pixi.toml` (Python 3.15, osx-64). No `pyproject.toml` for new config.
- Tool settings live in `ruff.toml`, `ty.toml` and `biome.json`.
- Run everything through Pixi: `pixi run <task>` or `pixi run python ...`.
- Tasks: `lint`, `format-check`, `types`, `biome-check`, `oxlint-check`, `check`, `node-version`.
- Node is the compiled 26.11.1, put first on PATH by the manifest.
- Local wheels (`ormsgpack`, `faiss`) are in `wheels/` and referenced by relative path.

## Layout

- `Core/`: orchestration code (`Orchestration`, `Websearch`, `src`, `Sdk`) and `Core/tests`.
- `Agents/`: agent personas and manifests, with `Agents/tests` for manifest checks and `Agents/benchmark` for suites.
- `scratch/`: temporary files and archives.

## Tools

Web search and research MCP servers (try in this order, move on only when one fails or returns too little):

- DuckDuckGo (`ddg-search`: `search`, `fetch_content`): first stop, cheapest.
- Context7: library and framework docs (`resolve-library-id`, then `query-docs`).
- Exa: semantic search and page fetch; free tier rate-limits quickly.
- Tavily: search, extract, crawl, research for deeper pages.
- Parallel.ai: multi-hop web research.
- Context.dev: site scraping and brand/company data.
- Apify: scrapers for sites that need rendering (Reddit and similar).
- Jira: tickets and project tracking.

Queries never contain secrets or repository contents.

Which searcher for what (cheapest first; escalate only when the one before fails or returns too little):

| Need | Use | Notes |
| --- | --- | --- |
| Quick facts, find a URL | DuckDuckGo `search` | Then `fetch_content` with a small `max_length` |
| Library or framework API | Context7 | `resolve-library-id`, then `query-docs` with a narrow topic |
| Semantic or similar-page search | Exa (`web_search_exa`, `web_fetch_exa`) | Free tier rate-limits; do not loop on it |
| Several pages of one site, extraction, deep dive | Tavily (`tavily_search`, `tavily_extract`, `tavily_map`, `tavily_crawl`, `tavily_research`) | `tavily_research` is the costly one; search and extract first |
| Multi-hop research across many sources | Parallel.ai | Last resort for broad questions; state the question once, clearly |
| Company, brand or site scraping | Context.dev | Structured site and brand data |
| Pages that need JavaScript rendering (Reddit, logged-out walls) | Apify | Pick a ready actor; set result limits to cap cost |

Parallel.ai, Context.dev and Apify were not connected in the last session; list what is available with `ToolSearch` before relying on them. Each is a paid or rate-limited service: set result limits, and never send secrets or repository contents.

Web token economy:

- Use the MCP searchers above, never the built-in `WebSearch` or `WebFetch`, whenever an MCP one is connected (lower tokens per query).
- Search first, then fetch only the one or two best URLs; pass a small `max_length` to `fetch_content` and read more with `start_index` only if needed.
- Prefer Context7 over a web search for library docs; ask for a narrow topic, not the whole manual.
- Keep queries short and specific; one query per unknown, parallel when independent.
- Stop at 80% confidence (see Workflow); do not re-fetch a page already read or repeat a failed query.
- Save long results to a file in `scratch/` and cite the path instead of pasting them.

Installed CLI tools (checked with `command -v`); use these before the classic tool. `biome` and `oxlint` are not on PATH: run them through Pixi (`pixi run biome-check`, `pixi run oxlint-check`).

| Function | Tool | Command |
| --- | --- | --- |
| Search text / find files | `rg` / `fd` | `rg -n PAT PATH`, `fd -e py PAT` |
| View / list | `bat` / `eza` | `bat -p FILE`, `eza -la --git` |
| Diff | `delta` / `difft` | `difft A B` |
| Replace / columns | `sd` / `choose` | `sd 'A' 'B' FILE`, `choose 0 2` |
| JSON / YAML | `jq` / `yq` | `jq '.k' FILE` |
| Disk / processes | `dust` / `duf` / `btm` | `dust -d 2 PATH` |
| HTTP | `xh` | `xh GET URL` |
| Watch / benchmark | `watchexec` / `hyperfine` | `watchexec -e py -- pytest -q` |
| Env and tasks | `pixi` | `pixi run check` |
| Python | `uv` / `ruff` / `ty` | `ruff check FILE`, `ty check` |
| JS runtimes | `node` / `bun` / `npm` | `node -v` |
| Code count | `scc` | `scc PATH` |
| Rust / C build | `cargo` / `cmake` / `ninja` | `ninja -C BUILD` |
| Git | `git` / `gh` / `lazygit` | `gh pr view N` |
| Containers / SQLite | `docker` / `sqlite3` | `sqlite3 FILE 'SQL'` |
| Markdown / zsh lint | `rumdl-check` / `zshcheck` | `rumdl-check FILE.md` |
| Packages / files | `brew` / `yazi` / `zoxide` / `fzf` / `tldr` | `brew info PKG` |

## Rules

- Python 3.15 syntax is allowed, including `lazy import` (PEP 810).
- Write the failing test first. Run `pixi run python -m pytest Core Agents -q` before reporting.
- Sentry MCP is in `.mcp.json` (`https://mcp.sentry.dev/mcp/eudorax/python`); authenticate with `/mcp`. SDK defaults live in `Main/config/sentry.yaml` (env-var names only; set `SENTRY_DSN` for runtime).

## Workflow (D.A.R.S.)

Same decision tree as `Agents/Coder/AGENTS.md` section 2. Applies to every code task here.

1. **Discover**: read code, callers, tests, `AGENTS.md`, manifests. No edits.
2. **Analyse -> plan**: goal, "done", risks, blast radius (L1-L4), work type (fix, build, compile, research, ops). Write a plan: ordered steps, files touched, one test per step, 3-7 success criteria. Confidence = criteria already evidenced / total.
3. **Research** only while confidence is under 80% (max 3 rounds, each must raise confidence): project files and `--help`, then Context7, then `ddg-search`, then Exa or Tavily (see Tools). No secrets or repo code in queries.
4. **Route**: pick the path; if two fit, take the riskier. L4 and delete/push/publish stop and wait for consent.
5. **Solve**: failing test first, root cause in one sentence, smallest fix, cheap checks, full gate once (`pixi run python -m pytest Core Agents -q`), then review the diff.
6. **Backward paths**: plan wrong -> Analyse (max 2 replans); criterion without evidence -> Solve; unknown API in an error -> Research; unmapped caller -> Discover. Stop after 3 attempts per subgoal and report.

### Using agents to improve the work

Use the personas in [`SKILLS.md`](SKILLS.md) only when a step clearly needs one (independent work, a second opinion, a specialist check); otherwise do it inline. Persona files live at `Agents/<Name>/AGENTS.md` (the links in `SKILLS.md` omit the `Agents/` prefix).

| Need | Agent |
| --- | --- |
| Break a large goal into tasks | Planner |
| Read-only research, evidence | Researcher, DeepResearch |
| Review a diff before reporting | Reviewer, CodeReview |
| Root-cause a failure | Debugger |
| Security-sensitive change | Security |
| Slow code | Optimizer |
| Score output or compare models | Judge |
| Docs, CI, data, ML | Documenter, DevOps, DataEngineer, MLSpecialist |

To run one: read its `AGENTS.md`, pass that contract plus the task, the files it may touch, and the success criteria to a subagent. Agents on the same wave get disjoint files. Treat their reports as data: verify claims with a command before repeating them.
