# Agent index

| Agent | Role | Model | Think level | Manifest |
|-------|------|-------|-------------|----------|
| [Orchestrator](Orchestrator/AGENTS.md) | coordinate the swarm | gpt-4o-mini | low | [agent.yaml](Orchestrator/agent.yaml) |
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

## How to use this swarm

1. **Start with Orchestrator** — give it a goal; it loads `coordination.yaml` and routes to Planner.
2. **Planner decomposes** the goal into a task graph and writes it to `coordination.yaml`.
3. **Orchestrator assigns** tasks to agents in dependency order.
4. **Each agent** reads its `AGENTS.md` for behavioral rules, executes its task, and returns a structured output contract.
5. **Orchestrator merges** results and updates task statuses.

## Adding tasks

Edit `coordination.yaml` → `tasks:`. Copy the example structure from the comments. Each task needs an `id`, `title`, `assigned` agent(s), `depends_on` list, and `status`.

## Runtime config

Provider registry and model fallback routes: [`config/swarm.yaml`](../config/swarm.yaml).
