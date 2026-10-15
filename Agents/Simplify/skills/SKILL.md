# Simplify Skill: Code Simplification & Indirection Reduction Engine

> **Scope**: Guard clauses, wrapper inlining, and cyclomatic complexity reduction patterns.

---

## 1. Early Return & Guard Clause Pattern

```python
# Before
def process_data(data):
    if data is not None:
        if len(data) > 0:
            if "status" in data:
                return data["status"]
    return None

# After (Simplified with Guard Clauses)
def process_data(data):
    if not data or "status" not in data:
        return None
    return data["status"]
```

---

## 2. Wrapper Collapse Pattern

```python
# Before (Unnecessary Pass-Through Wrapper)
def get_user_name(user):
    return _fetch_name_internal(user)

def _fetch_name_internal(user):
    return user.name

# After (Inlined)
def get_user_name(user):
    return user.name
```
