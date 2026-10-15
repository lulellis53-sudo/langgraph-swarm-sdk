---
name: LearnAskmode
description: >
  Run Grok /learn in askmode (step). Collect session traces, launch
  learn-traces, present the report, then apply only picker ids. Use when
  the user says /learn, learn from my traces, Extra/Learn, or askmode learn.
---

# Learn askmode

Read `$GROK_HOME/bundled/skills/learn/SKILL.md` for askmode rules. Run `state.py` and `collect_sessions.py` from this persona's `python/` folder. That folder is `args.skill_dir`.

This persona locks **mode = step**. Ask mode + scope once on a Neutral invoke. Present the report in its own turn. One picker per group after that.

## Do

1. Probe `state.py get` with `python`, then `py -3`, then `python3`.
2. Price with `collect_sessions.py --estimate`, then collect.
3. Launch workflow `learn-traces` with `args` as an object. Block on `state.py wait`.
4. Apply picked action ids only. Record `deferred` for the rest. `state.py decide` after each apply.

## Do not

- Do not use `auto` unless the user named it.
- Do not open a picker in the same turn as the report.
- Do not retire surfaces when `disuse_evidence.sufficient` is false.
- Do not write `report.md` yourself from a stalled synthesis.
