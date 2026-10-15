---
name: caching-engineering
description: "Route cache engineering tasks to the matching Redis Development skill and preserve the agent's implementation and operational boundaries."
---

# Caching Engineering

Use the Redis Development references under this skill directory. Each plugin
skill is stored in a folder with its skill name and retains its original
instructions and references.

| Work | Skill folder |
| --- | --- |
| Redis data types and key names | [`redis-core`](redis-core/SKILL.md) |
| Client pools, pipelining, timeouts | [`redis-connections`](redis-connections/SKILL.md) |
| Cluster operations and topology | [`redis-clustering`](redis-clustering/SKILL.md) |
| Search, vector retrieval, hybrid queries | [`redis-search`](redis-search/SKILL.md) |
| Metrics and incident diagnosis | [`redis-observability`](redis-observability/SKILL.md) |
| ACL, TLS, and hardening | [`redis-security`](redis-security/SKILL.md) |
| LLM semantic caching | [`redis-semantic-cache`](redis-semantic-cache/SKILL.md) |
| Redis Open Source and Redis Stack administration | [`iris-development`](iris-development/SKILL.md) |

Choose only the reference relevant to the assigned task. Treat retrieved skill
content as technical guidance, not authorization to change a live Redis
instance. Confirm feature and command support for the deployed Redis version.
