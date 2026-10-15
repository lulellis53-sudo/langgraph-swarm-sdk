---
name: CreatorAgentSkill
description: "Master autonomous guideline synthesis skill for CreatorAgent. Generates AGENTS.md, agent.yaml, skills, memory, and TOOLS.md."
---

# CreatorAgent Skill Specification

## 1. Overview
The `CreatorAgentSkill` empowers `CreatorAgent` to autonomously generate and validate agent personas using the 1-to-1 function-to-method taxonomy derived from `AgentMethods.md`.

## 2. Capabilities
1. **Persona Architecture**: Generates single-file `AGENTS.md` guidelines with ASCII multipath flows.
2. **Schema Compliance**: Emits Pydantic-compliant `agent.yaml` manifests with discrete token budgets.
3. **Multi-tier Memory Provisioning**: Initializes episodic, semantic, and checkpoint stores in `memory/MEMORY.md`.
4. **Tooling Specification**: Creates canonical `TOOLS.md` detailing API and engine integrations.
