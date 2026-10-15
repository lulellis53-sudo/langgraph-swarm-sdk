# FuzzEngineer Skill: Property-Based Testing & Fuzzing Engine

> **Scope**: Property testing strategies (Hypothesis), boundary mutation algorithms, and crash reproduction harness synthesis.

---

## 1. Property-Based Testing Patterns

### 1.1 Invariant Assertions
```python
from hypothesis import given, strategies as st

@given(st.text(), st.integers(min_value=1, max_value=60000))
def test_parser_invariant(input_string, max_ms):
    # Invariant: Parser should never raise unhandled TypeError or AttributeError
    try:
        result = parse_input(input_string, max_ms)
        assert result is not None
    except ValueError:
        pass # Explicit domain error allowed
```

---

## 2. Boundary Mutation Strategies

1. **Null Byte Injection**: Insert `\x00` and non-printable Unicode characters.
2. **Buffer Overflow Strings**: Generate long string sequences exceeding 64KB.
3. **Numeric Boundary Floats**: Inject `NaN`, `Infinity`, `-Infinity`, and integer overflow boundaries.
4. **Malformed JSON Payloads**: Truncate brackets, introduce illegal escapes, and inject unquoted keys.
