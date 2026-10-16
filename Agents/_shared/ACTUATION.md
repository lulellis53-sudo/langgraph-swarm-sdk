# Swarm specialist actuation (DARS · ReAct · Reflection · SWE)

Every persona uses the same **four-layer** loop after the
[Jev multirouter](JEV_MULTIROUTER.md) selects the agent and model tier. Details:
[`../AgentMethods.md`](../AgentMethods.md).

```text
[ inbound task ] → Jev multirouter → DARS → ReAct → Reflection
       ↑__________________________________|  backward (MR2–MR4 / B1–B4); see JEV_REFLECT_AUTOLEARN.md
       └ autolearn buffer on measured misroute / benchmark Δ
→ handoff JSON
```

Config and benchmarks: root `CLAUDE.md`, `pixi run benchmark`.
