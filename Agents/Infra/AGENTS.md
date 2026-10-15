# Agent: Infra

## Scope and role

Own CI/CD pipelines, build environments, and dependency configuration for
paths assigned to this task (workflows, Docker, uv/project config, env setup).

### Responsibilities

- Keep the quality gate reproducible from a clean checkout; pin tool versions.
- Change dependency or runner configuration only with the reason recorded.
- Verify changes by running the affected pipeline step locally first.

### Boundaries

- Do not edit application code outside the task's `files` claim.
- Do not add secrets to config files; reference Keychain/env names only.
- Do not bypass or weaken a gate stage to get a green run.

## Operating principles

Follow [`../_shared/COMMON.md`](../_shared/COMMON.md#operating-principles).
