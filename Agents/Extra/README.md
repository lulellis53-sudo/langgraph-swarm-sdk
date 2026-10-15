# Extra personas

Off the handoff glob (`Agents/*/agent.yaml`). Not loaded by `swarm_sdk.agents` unless copied to a top-level `Agents/<Name>/` folder. Do not add Extra names to `coordination.yaml` without that top-level manifest.

| Agent | Role | Manifest |
| --- | --- | --- |
| [CreatorAgent](CreatorAgent/AGENTS.md) | synthesize agent guidelines | [agent.yaml](CreatorAgent/agent.yaml) |
| [FileManager](FileManager/AGENTS.md) | extract, reverse engineer, convert formats | [agent.yaml](FileManager/agent.yaml) |
| [Learn](Learn/AGENTS.md) | Grok `/learn` traces in askmode (step) | [agent.yaml](Learn/agent.yaml) |
| [Benchmarker](Benchmarker/AGENTS.md) | consolidated into Benchmarket | [agent.yaml](Benchmarker/agent.yaml) |
| [Normalizer](Normalizer/AGENTS.md) | text & data normalization | [agent.yaml](Normalizer/agent.yaml) |
| [Prediction](Prediction/AGENTS.md) | time-series & event prediction | [agent.yaml](Prediction/agent.yaml) |
| [PromptEvaluator](PromptEvaluator/AGENTS.md) | prompt quality evaluation | [agent.yaml](PromptEvaluator/agent.yaml) |
| [TokenSaver](TokenSaver/AGENTS.md) | token minimization strategies | [agent.yaml](TokenSaver/agent.yaml) |
| [AgentCompacting](AgentCompacting/AGENTS.md) | session compaction & memory summarization | [agent.yaml](AgentCompacting/agent.yaml) |
| [Playwright](Playwright/AGENTS.md) | browser decision, LLM model manager, hit/text critic (sole-owned by Websearcher) | [agent.yaml](Playwright/agent.yaml) |
