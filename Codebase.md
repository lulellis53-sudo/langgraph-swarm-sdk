# Codebase Map

Map of `~/Desktop/Workspace` as of 2026-10-15. Sizes are measured with `scc`
(`.git`, `.pixi`, `py315`, `wheels`, `scratch` excluded). Descriptions marked
*inferred* come from folder names and manifests, not from running the code.

## At a glance

| Item | Value |
| --- | --- |
| Files / lines | 1,510 files, 148,922 lines |
| Python | 485 files, 61,527 code lines |
| Markdown | 366 files, 40,754 lines (agent contracts, docs) |
| YAML | 184 files, 6,486 lines (agent manifests, configs) |
| Environment | Pixi (`pixi.toml`): Python 3.15, osx-64, Node 26.11.1 first on PATH |
| Tool config | `ruff.toml`, `ty.toml`, `biome.json` (no new `pyproject.toml` config) |
| Git | branch `cursor/token-plan-llm-routes`; most folders are untracked |

## Top-level layout

Taxonomy (set by the owner):

| Path | Role |
| --- | --- |
| `Core/` | LangChain-related code: `Orchestration`, `Websearch` (frontend/midend/backend), `src`, `Sdk`, `tests` |
| `Agents/` | Agent configs, models and contracts: one folder per agent (`AGENTS.md`, `agent.yaml`, `config/`, `skills/`, `memory/`) |
| `Modules/` | Engines for future use: `Modules/Prediction` (`ForecastEngine`, `ForecastConfig`, lance store, web evidence) |
| `Tools/` | Agent tooling: `Tools/WebSearch` (search, scrape, extract pipeline, CLI, benchmarks) |
| `Farm/` | Future stage: `Farm/BotDeal` (deals/arbitrage), `Farm/TechNews` (news pipeline package `technews`) |

Other root items: `PyStart/` (separate starter project), `coordination.yaml`
(agent registry and task board), `wheels/` and `py315/` (local wheels, Python 3.15
build area), `scratch/` (temporary files, not always present).

`Learn` and `Tester` at the root are broken symlinks (to `Extra/Learn` and
`Benchmarket`); they point nowhere.

## Agents (`Agents/`)

About 50 personas. Grouped by role (*inferred from folder names*):

- **Coordination:** Orchestrator, Planner, Judge, ModelDelegate, Worktree
- **Coding:** Coder, PythonCoder, RustCoder, CCoder, CodeFixer, CodeBaser, Refactor, Optimizer, Simplify, Debugger, Compilator
- **Review and quality:** CodeReview, Reviewer, Security, FuzzEngineer, Benchmarker, Benchmarket, PromptEvaluator, Tuner
- **Research and web:** DeepResearch, DeepWebSearch, Researcher, WebResearcher, Websearcher, WebFetch
- **Data and infra:** DataEngineer, Databaser, Caching, RAG, MemoryGraphBuilder, Normalizer, TxtToCsv, Infra, DevOps, ApiDesigner, ApiVaulter
- **Docs and writing:** Documenter, GuideCreator, Writer, Architect, MLSpecialist, ShellMaster, TokenSaver

Each agent folder follows the same contract: `AGENTS.md` (role, workflow,
output schema), `agent.yaml` (model, tasks, capabilities, telemetry),
`config/models.yaml` (primary and fallback models, circuit breaker), `skills/`,
`memory/`. Agents named in `coordination.yaml` are wired into the swarm.

Tests for agents: `Agents/tests` (manifest checks) and `Agents/_test`
(model delegation, effort, A/B and search-quality scripts).

## Data flow (high level)

```text
query -> Tools/WebSearch frontend (dorks, providers, hits)
      -> midend (fetch, extract, rank)
      -> backend (store, vectors)
      -> agents (Researcher / DeepResearch) -> Judge (score, verdict)
Farm/TechNews: scrape -> store -> Prediction (forecast) -> newsletter -> site
```

Flow is *inferred* from the READMEs and package layout, not traced end to end.

## Commands

All run through Pixi from the workspace root:

| Task | Command |
| --- | --- |
| Lint / format check | `pixi run lint`, `pixi run format-check` |
| Types | `pixi run types` |
| JS lint | `pixi run biome-check`, `pixi run oxlint-check` |
| All checks | `pixi run check` |
| Tests | `pixi run python -m pytest Core Agents -q` |

Rules from `CLAUDE.md`: write the failing test first, Python 3.15 syntax
(including `lazy import`) is allowed, secrets never go in code or logs.

## Known issues

- Root `README.md` and `SKILLS.md` link to `Reviewer/`, `DeepResearch/`,
  `Prediction/` and others at the root; those moved under `Agents/` or `Modules/`.
- `../_shared/COMMON.md`, linked from several `AGENTS.md` files, does not exist.
- `from Modules.Prediction import ...` needs the workspace root on `PYTHONPATH`
  (works under `pixi run pytest` from the root). `ruff.toml` `src` still lists `Prediction`.
- `Modules/Prediction/test_engine.py` fails here: `lightgbm` is not installed.
- Agent manifest tests only check that a name and skills files exist, so they
  pass trivially (see the DeepResearch vs DeepWebSearch judgment).
- `DeepResearch` and `DeepWebSearch` overlap (DeepWebSearch says it was merged
  into DeepResearch) and have conflicting model settings.
