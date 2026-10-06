# Security

Do not open a public GitHub issue for a vulnerability or a leaked credential.

## Report a vulnerability

1. Prefer **GitHub private vulnerability reporting** on this repository (Security tab → Report a vulnerability).
2. If that is not enabled, email the maintainer listed in `pyproject.toml` (`authors`).

Include:

- Affected paths or config keys (not secret **values**)
- Impact and a minimal reproduction
- Whether the issue is already public

We will acknowledge the report, confirm the issue, and ship a fix or mitigation when we can.

## Secrets in this project

- Never commit `.env`, API keys, tokens, or Keychain dumps.
- Config YAML (`agent.yaml`, `model_registry.yaml`, `swarm.yaml`) holds env-var **names** only.
- Agent output and issues should cite a path or pattern, not the secret itself. See [Agents/Security/AGENTS.md](Agents/Security/AGENTS.md).

## Supported versions

Only the latest published version on `main` is supported unless a release notes a longer window.
