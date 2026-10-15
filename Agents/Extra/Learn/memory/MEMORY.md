# Agent Memory: Learn

> **Agent Memory Ledger**: Episodic learn-run pointers for Extra/Learn. No secrets.

---

## 1. Memory Store Architecture

- **Episodic Memory**: Last completed run dir, mode, scope, sessions kept, applied skill names.
- **Semantic Cache**: None. Phrase ownership lives in user `SKILL.md` files.
- **Checkpoint Ledger**: `state.py decide` lines and trash originals under `$GROK_HOME/learn/trash/`.

---

## 2. Invariants & Isolation

1. **Zero Secret Leakage**: Names and paths only. Never store tokens, headers, or env values.
2. **Run identity**: Record `run_dir` and `run name` (last path component) after collect.
3. **Askmode**: Default mode is `step`. Record overrides only when the user named `auto` or `report`.
