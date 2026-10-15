# Refactor Skill: CodeCleaner Engine

> **Scope**: Dead code elimination, unused imports cleanup, dependency pruning, and structural AST reachability analysis.

---

## 1. CodeCleaner Dead Code Elimination Protocol

### 1.1 Unused Import & Symbol Pruning
1. Identify zero-reference imports using AST reachability analysis (`vulture`, `unimport`, `ast-grep`).
2. Verify zero dynamic usages (reflection, DI containers, `__all__` exports, string lookups).
3. Safely delete unused statements in isolated, provably green steps.

### 1.2 Dependency Tree Pruning
1. Audit project manifests (`pyproject.toml`, `package.json`, `Cargo.toml`).
2. Identify dependencies declared but never imported across the workspace.
3. Remove unreferenced packages and sync project lockfiles.

---

## 2. AST Reachability Analysis Pattern

```python
import ast

def analyze_symbol_reachability(source_code: str) -> set[str]:
    """Parse AST and return set of referenced global identifiers."""
    tree = ast.parse(source_code)
    referenced = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            referenced.add(node.id)

    return referenced
```
