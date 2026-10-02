# Repository layout

```
Swarm/
├── .cursor/              # Cursor project settings + extension recommendations
├── .vscode/              # VS Code / Cursor workspace settings (shared)
├── Agents/               # Per-role AGENTS.md + agent.yaml manifests
├── benchmark/            # Task harness (Tasks/{name}/)
├── codeworkspace/        # swarm.code-workspace (multi-root)
├── config/               # swarm.yaml runtime wiring
├── docs/                 # Contributor layout and notes
├── proto/                # gRPC definitions
├── src/swarm_sdk/        # Python package
├── tests/                # Unit tests + fakes
├── pyproject.toml
├── uv.lock
└── README.md             # Product docs + codebase rules
```

## IDE

- Open the repo root, or **File → Open Workspace** → `codeworkspace/swarm.code-workspace`.
- Install recommended extensions when prompted (Ruff, Python, YAML, ty).
- Interpreter: `.venv` after `uv sync --python 3.14.5 --extra dev`.

## Related paths

| Concern | Path |
|---------|------|
| Agent coordination | `Agents/coordination.yaml` |
| Model / hybrid config | `config/swarm.yaml` |
| CI | `.github/workflows/` |
| Lint config | `pyproject.toml` `[tool.ruff]`, `.yamllint.yml` |
