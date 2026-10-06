## Summary

<!-- Why this change exists. Link issues with Fixes #N when applicable. -->

## Test plan

- [ ] Quality gate (or targeted pytest + ruff + ty for the touched area)
- [ ] `uv run python -m swarm_sdk.agents.validate` if `Agents/` or coordination YAML changed
- [ ] Regenerated protobuf stubs if `swarm.proto` changed
- [ ] No secrets, `.env`, or credential values in the diff

## Notes

<!-- Breaking API / config / env var names (`SWARM_*`). Leave blank if none. -->
