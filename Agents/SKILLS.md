# Agent index

| Agent | Role | LangGraph node | Model (predefined) | Manifest |
|-------|------|----------------|--------------------|----------|
| Orchestrator | coordinates the swarm | — | openai:gpt-4o-mini | [agent.yaml](Orchestrator/agent.yaml) |
| Planner | task graphs | — | openai:gpt-4o-mini | [agent.yaml](Planner/agent.yaml) |
| Researcher | read-only research | researcher | openai:gpt-4o-mini | [agent.yaml](Researcher/agent.yaml) |
| Coder | implements code | coder | openai:gpt-4o | [agent.yaml](Coder/agent.yaml) |
| Reviewer | reviews diffs | reviewer | openai:gpt-4o | [agent.yaml](Reviewer/agent.yaml) |
| Tester | pytest | — | openai:gpt-4o-mini | [agent.yaml](Tester/agent.yaml) |
| Debugger | root cause | — | openai:gpt-4o-mini | [agent.yaml](Debugger/agent.yaml) |
| Documenter | docs | — | openai:gpt-4o-mini | [agent.yaml](Documenter/agent.yaml) |
| DevOps | CI/CD | — | openai:gpt-4o-mini | [agent.yaml](DevOps/agent.yaml) |
| Security | security review | — | openai:gpt-4o | [agent.yaml](Security/agent.yaml) |
| DataEngineer | vector stores | — | openai:gpt-4o-mini | [agent.yaml](DataEngineer/agent.yaml) |
| MLSpecialist | embeddings | — | openai:gpt-4o | [agent.yaml](MLSpecialist/agent.yaml) |
| Optimizer | performance | — | openai:gpt-4o-mini | [agent.yaml](Optimizer/agent.yaml) |

Runtime providers and fallback routes: [config/swarm.yaml](../config/swarm.yaml). Task board: [coordination.yaml](coordination.yaml).
