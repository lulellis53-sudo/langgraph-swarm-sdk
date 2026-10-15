# Agent Tools Specification: Learn

> **Authoritative Specification**: Grok `/learn` helpers for Extra/Learn askmode.

---

## 1. Core Tooling Catalog

1. **Interpreter probe** — first of `python`, `py -3`, `python3` that prints JSON from `python/state.py get`.
2. **Collectors and ledger** (this persona, [`python/`](python/)):
   - `state.py get|set|wait|decide|trash|restrict`
   - `collect_sessions.py` (`--estimate`, `--days`, `--since-last`, `--limit`)
3. **Workflow** — `python/learn-traces.rhai`. Prefer the named workflow `learn-traces`; pass `args.skill_dir` as this `python/` folder, `args` as a JSON object.
4. **Consent** — `ask_user_question` once per curation group (max eight options; split if larger).
5. **Manifest check** (persona files only): `uv run python -m swarm_sdk.agents.validate`

This Extra persona is **not** on `Agents/*/agent.yaml`. `load_all` does not glob `Extra/`. Do not add `Learn` to `coordination.yaml` unless a top-level `Agents/Learn/agent.yaml` exists.

## 2. Artifact paths

| Artifact | Path |
| --- | --- |
| Skill dir (Python) | [`python/`](python/) (`collect_sessions.py`, `state.py`) |
| Askmode rules | `$GROK_HOME/bundled/skills/learn/SKILL.md` |
| Run dir | `$GROK_HOME/learn/runs/<UTC>/` |
| Report | `<run>/report.md` |
| Actions | `<run>/actions.json` |
| Decisions | `$GROK_HOME/learn/decisions.jsonl` |
| Undo trash | `$GROK_HOME/learn/trash/<run name>/` |
