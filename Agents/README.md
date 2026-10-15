# Agent index

| Agent | Role | Model | Think level | Manifest |
|-------|------|-------|-------------|----------|
| [Orchestrator](Orchestrator/AGENTS.md) | coordinate the swarm | gpt-4o-mini | low | [agent.yaml](Orchestrator/agent.yaml) |
| [ModelDelegate](Extra/ModelDelegate/AGENTS.md) | pick provider/model routes and GPU dispatch | openrouter:z-ai/glm-5.3-flash | low | [agent.yaml](Extra/ModelDelegate/agent.yaml) |
| [Planner](Planner/AGENTS.md) | decompose goals into task graphs | gpt-4o-mini | high | [agent.yaml](Planner/agent.yaml) |
| [Researcher](Extra/Researcher/AGENTS.md) | read-only research and synthesis | gpt-4o-mini | medium | [agent.yaml](Extra/Researcher/agent.yaml) |
| [Coder](Coder/AGENTS.md) | implement code changes | gpt-4o | high | [agent.yaml](Coder/agent.yaml) |
| [Reviewer](Reviewer/AGENTS.md) | review diffs and PRs | gpt-4o | high | [agent.yaml](Reviewer/agent.yaml) |
| [Tester](Tester/AGENTS.md) | write and run tests | gpt-4o-mini | medium | [agent.yaml](Tester/agent.yaml) |
| [Debugger](Debugger/AGENTS.md) | root-cause failures | gpt-4o-mini | high | [agent.yaml](Debugger/agent.yaml) |
| [Documenter](Documenter/AGENTS.md) | maintain documentation | gpt-4o-mini | low | [agent.yaml](Documenter/agent.yaml) |
| [DevOps](Extra/DevOps/AGENTS.md) | CI/CD and environments | gpt-6-luna | medium | [agent.yaml](Extra/DevOps/agent.yaml) |
| [Watchtower](Extra/Watchtower/AGENTS.md) | signed Sentry event triage and safe escalation | gpt-6-luna | high | [agent.yaml](Extra/Watchtower/agent.yaml) |
| [Worktree](Extra/Worktree/AGENTS.md) | multi-lane git worktrees | gpt-6-luna | medium | [agent.yaml](Extra/Worktree/agent.yaml) |
| [Security](Extra/Security/AGENTS.md) | security review and auditing | gpt-4o | high | [agent.yaml](Extra/Security/agent.yaml) |
| [DataEngineer](Extra/DataEngineer/AGENTS.md) | data pipelines and storage | gpt-4o-mini | medium | [agent.yaml](Extra/DataEngineer/agent.yaml) |
| [MLSpecialist](Extra/MLSpecialist/AGENTS.md) | model evaluation and integration | gpt-4o | high | [agent.yaml](Extra/MLSpecialist/agent.yaml) |
| [Optimizer](Extra/Optimizer/AGENTS.md) | performance tuning | gpt-4o-mini | medium | [agent.yaml](Extra/Optimizer/agent.yaml) |
| [Benchmarker](Extra/Benchmarker/AGENTS.md) | workloads, baselines, suites & regression gates | gpt-6-luna | medium | [agent.yaml](Extra/Benchmarker/agent.yaml) |
| [Refactor](Extra/Refactor/AGENTS.md) | safe incremental refactors | gpt-4o | high | [agent.yaml](Extra/Refactor/agent.yaml) |
| [TxtToCsv](Extra/TxtToCsv/AGENTS.md) | convert text files to CSV | gpt-4o-mini | low | [agent.yaml](Extra/TxtToCsv/agent.yaml) |
| [RAG](Extra/RAG/AGENTS.md) | semantic caching, hybrid search, reranking & grounding | inherit | high | [agent.yaml](Extra/RAG/agent.yaml) |
| [DeepResearch](Extra/DeepResearch/AGENTS.md) | deep technical research & evidence graphs | inherit | high | [agent.yaml](Extra/DeepResearch/agent.yaml) |
| [math](Extra/math/AGENTS.md) | symbolic/numerical solving and verification | moonshot:kimi-k2.7-code | high | [agent.yaml](Extra/math/agent.yaml) |
| [WebFetch](Extra/WebFetch/AGENTS.md) | deterministic pipeline stage: fetch/render | none (no LLM) | - | [agent.yaml](Extra/WebFetch/agent.yaml) |
| [Normalizer](Extra/Normalizer/AGENTS.md) | deterministic pipeline stage: normalize + dedupe | none (no LLM) | - | [agent.yaml](Extra/Normalizer/agent.yaml) |
| [Persister](Extra/Persister/AGENTS.md) | deterministic pipeline stage: SQLite store | none (no LLM) | - | [agent.yaml](Extra/Persister/agent.yaml) |
| [Prediction](Extra/Prediction/AGENTS.md) | mlforecast lane (`ForecastEngine`) | inherit | medium | [agent.yaml](Extra/Prediction/agent.yaml) |
| [Newsletter](Extra/Newsletter/AGENTS.md) | offline digest MVP | gpt-4o-mini | low | [agent.yaml](Extra/Newsletter/agent.yaml) |

Imported reference catalog: [`antigravity-imported/`](antigravity-imported/) holds 21 Antigravity personas
(`AGENTS.md` + `agent.md`, frontmatter contracts) — reference material for prompt design, **not** active
swarm manifests; they are not loaded by `swarm_sdk.agents` and are excluded from the table above.

**Actuation:** [`_shared/ACTUATION.md`](_shared/ACTUATION.md) · [`AgentMethods.md`](AgentMethods.md).  
Canonical research/review personas: [DeepResearch](Extra/DeepResearch/AGENTS.md), [Reviewer](Reviewer/AGENTS.md) (duplicate `code-review/` / `deep-research/` folders removed).

## How to use this swarm

1. **Start with Orchestrator** — give it a goal; it loads `coordination.yaml` and routes to Planner.
2. **ModelDelegate picks routes** — for each sub-task it selects the cheapest capable model/provider and a fallback chain, preferring GPU embedding/math when available.
3. **Planner decomposes** the goal into a task graph and writes it to `coordination.yaml`.
4. **Orchestrator assigns** tasks to agents in dependency order.
5. **Each agent** reads its `AGENTS.md` for behavioral rules, executes its task, and returns a structured output contract.
6. **Orchestrator merges** results and updates task statuses.

Each agent also has a [`Benchmarks/`](Coder/Benchmarks/) folder for role-scoped case notes and thresholds; shared runners live under [`benchmark/`](benchmark/).

Python modules (all personas): [`_shared/COMMON.md`](_shared/COMMON.md#python-modules).

## Adding or editing agents

Before creating an agent or editing an existing persona, read and analyze
[`TEMPLATE.md`](TEMPLATE.md). Use it to decide which sections apply, follow its
lean-profile guidance, and verify the persona's role, permissions, workflow,
validation, and handoff contract. Then adapt the relevant guidance to the
agent; do not copy unverified examples or retain irrelevant sections. When
updating an agent manifest, run the template sync command documented in
[`TEMPLATE.md`](TEMPLATE.md) and review the resulting diff.

Authoring workflow: [`AgentMethods.md`](AgentMethods.md) Part I. Cursor skill: `.cursor/skills/agent-creator/SKILL.md`.

## Adding or editing agents

Before creating an agent or editing an existing persona, read and analyze
[`TEMPLATE.md`](TEMPLATE.md). Use it to decide which sections apply, follow its
lean-profile guidance, and verify the persona's role, permissions, workflow,
validation, and handoff contract. Then adapt the relevant guidance to the
agent; do not copy unverified examples or retain irrelevant sections. When
updating an agent manifest, run the template sync command documented in
[`TEMPLATE.md`](TEMPLATE.md) and review the resulting diff.

## Adding tasks

Edit `coordination.yaml` → `tasks:`. Copy the example structure from the comments. Each task needs an `id`, `title`, `assigned` registered agent(s), `depends_on` list, and `status`; `task` optionally selects a task ID from that agent's manifest. Coder tasks that should share a wave also need disjoint `files` (and usually `task: implement_in_files`). A production file and the tests that cover it stay on the same Coder task.

## Runtime config

Provider registry and model fallback routes: [`Main/config/swarm.yaml`](../Main/config/swarm.yaml).
