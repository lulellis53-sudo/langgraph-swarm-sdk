# Agent Tools Specification: CreatorAgent

> **Authoritative Specification**: Tooling, validation engines, and guideline linters for `CreatorAgent`.

---

## 1. Core Tooling Catalog

1. **Manifest Validator**:
   - `uv run python -m swarm_sdk.agents.validate`: Validates all manifests against Pydantic models.
2. **AST & Syntax Linters**:
   - `ruff check`: Validates Python syntax and formatting.
   - `npx -y @biomejs/biome check`: Validates JSON schemas and manifests.
3. **Template Engine**:
   - Accesses canonical patterns in [`docs/methods.md`](docs/methods.md) and [`docs/templates.md`](docs/templates.md).
