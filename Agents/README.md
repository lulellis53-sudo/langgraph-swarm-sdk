# Agent index

| Agent | Role | Model | Think level | Manifest |
|-------|------|-------|-------------|----------|
| [Orchestrator](Orchestrator/AGENTS.md) | coordinate the swarm | gpt-4o-mini | low | [agent.yaml](Orchestrator/agent.yaml) |
| [ModelDelegate](ModelDelegate/AGENTS.md) | pick provider/model routes and GPU dispatch | openrouter:z-ai/glm-5.3-flash | low | [agent.yaml](ModelDelegate/agent.yaml) |
| [Planner](Planner/AGENTS.md) | decompose goals into task graphs | gpt-4o-mini | high | [agent.yaml](Planner/agent.yaml) |
| [Researcher](Researcher/AGENTS.md) | read-only research and synthesis | gpt-4o-mini | medium | [agent.yaml](Researcher/agent.yaml) |
| [Coder](Coder/AGENTS.md) | implement code changes | gpt-4o | high | [agent.yaml](Coder/agent.yaml) |
| [Reviewer](Reviewer/AGENTS.md) | review diffs and PRs | gpt-4o | high | [agent.yaml](Reviewer/agent.yaml) |
| [Tester](Tester/AGENTS.md) | write and run tests | gpt-4o-mini | medium | [agent.yaml](Tester/agent.yaml) |
| [Debugger](Debugger/AGENTS.md) | root-cause failures | gpt-4o-mini | high | [agent.yaml](Debugger/agent.yaml) |
| [Documenter](Documenter/AGENTS.md) | maintain documentation | gpt-4o-mini | low | [agent.yaml](Documenter/agent.yaml) |
| [DevOps](DevOps/AGENTS.md) | CI/CD and environments | gpt-4o-mini | medium | [agent.yaml](DevOps/agent.yaml) |
| [Security](Security/AGENTS.md) | security review and auditing | gpt-4o | high | [agent.yaml](Security/agent.yaml) |
| [DataEngineer](DataEngineer/AGENTS.md) | data pipelines and storage | gpt-4o-mini | medium | [agent.yaml](DataEngineer/agent.yaml) |
| [MLSpecialist](MLSpecialist/AGENTS.md) | model evaluation and integration | gpt-4o | high | [agent.yaml](MLSpecialist/agent.yaml) |
| [Optimizer](Optimizer/AGENTS.md) | performance tuning | gpt-4o-mini | medium | [agent.yaml](Optimizer/agent.yaml) |
| [Refactor](Refactor/AGENTS.md) | safe incremental refactors | gpt-4o | high | [agent.yaml](Refactor/agent.yaml) |
| [TxtToCsv](TxtToCsv/AGENTS.md) | convert text files to CSV | gpt-4o-mini | low | [agent.yaml](TxtToCsv/agent.yaml) |
| [RAG](RAG/AGENTS.md) | retrieval, grounding, and semantic cache policy | inherit | high | [agent.yaml](RAG/agent.yaml) |
| [math](math/AGENTS.md) | symbolic and numerical mathematics | mistral:ministral-3-8b-latest | high | [agent.yaml](math/agent.yaml) |
| [DeepResearch](DeepResearch/AGENTS.md) | sourced multi-hop synthesis | inherit | high | [agent.yaml](DeepResearch/agent.yaml) |
| [WebResearcher](WebResearcher/AGENTS.md) | narrow cited web lookup | gpt-4o-mini | medium | [agent.yaml](WebResearcher/agent.yaml) |
| [Newsletter](Newsletter/AGENTS.md) | digest from supplied snippets | gpt-4o-mini | low | [agent.yaml](Newsletter/agent.yaml) |
| [ApiDesigner](ApiDesigner/AGENTS.md) | interface contracts and compatibility | gpt-4o | high | [agent.yaml](ApiDesigner/agent.yaml) |
| [Architect](Architect/AGENTS.md) | package and directory boundaries | gpt-4o | high | [agent.yaml](Architect/agent.yaml) |
| [Toolchain](Toolchain/AGENTS.md) | compilers, linkers, and build flags | gpt-4o | high | [agent.yaml](Toolchain/agent.yaml) |
| [Benchmarker](Benchmarker/AGENTS.md) | measured baselines and comparisons | gpt-4o-mini | medium | [agent.yaml](Benchmarker/agent.yaml) |
| [WebFetch](WebFetch/AGENTS.md) | deterministic stage: fetch and render | none (no LLM) | - | [agent.yaml](WebFetch/agent.yaml) |
| [Normalizer](Normalizer/AGENTS.md) | deterministic stage: normalize and dedupe | none (no LLM) | - | [agent.yaml](Normalizer/agent.yaml) |
| [Persister](Persister/AGENTS.md) | deterministic stage: store documents | none (no LLM) | - | [agent.yaml](Persister/agent.yaml) |

`benchmark/` is the test harness, not an agent. Do not add `Agents/Benchmark/`: on a case-insensitive volume it is the same directory. Nested folders such as `ModelDelegate/MathWorker/` are dispatch helpers. The loader reads only `Agents/*/agent.yaml`.

## How to use this swarm

1. **Start with Orchestrator** — give it a goal; it loads `coordination.yaml` and routes to Planner.
2. **ModelDelegate picks routes** — for each sub-task it selects the cheapest capable model/provider and a fallback chain, preferring GPU embedding/math when available.
3. **Planner decomposes** the goal into a task graph and writes it to `coordination.yaml`.
4. **Orchestrator assigns** tasks to agents in dependency order.
5. **Each agent** reads its `AGENTS.md` for behavioral rules, executes its task, and returns a structured output contract.
6. **Orchestrator merges** results and updates task statuses.

Each agent has an `AGENTS.md` role contract (persona, decision tree or multipath workflow, tasks, JSON output) and an `agent.yaml` manifest. The loader does not read a JSON twin of the manifest.

Shared runners live under [`benchmark/`](benchmark/).

## Adding tasks

Edit `coordination.yaml` → `tasks:`. Copy the example structure from the comments. Each task needs an `id`, `title`, `assigned` registered agent(s), `depends_on` list, and `status`; `task` optionally selects a task ID from that agent's manifest. Coder tasks that should share a wave also need disjoint `files` (and usually `task: implement_in_files`). A production file and the tests that cover it stay on the same Coder task.

## Runtime config

Provider registry and model fallback routes: [`Main/config/swarm.yaml`](../Main/config/swarm.yaml).
