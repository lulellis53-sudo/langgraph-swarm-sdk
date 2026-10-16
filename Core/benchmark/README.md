# Core benchmarks

Small, CI-friendly offline benchmarks for Core (not a port of `Swarm/Agents/benchmark`).

## Run

```bash
pixi run benchmark
```

Or a single task:

```bash
pixi run python -m Core.benchmark.run --task orchestration_graph
pixi run python -m Core.benchmark.run --task jev_agent_routing
pixi run python -m Core.benchmark.run --task all
```

## Tasks

| Task | Description |
| --- | --- |
| `orchestration_graph` | Timed `build_graph` → `invoke` with `FakeListChatModel` |
| `jev_agent_routing` | Golden swarm goals → `JevRouter.evaluate_choice` (accuracy ≥ 85%, p50 ≤ 35 ms) |

Pytest coverage lives under `Core/benchmark/tasks/*/test_*.py` and is included in `pixi run test`.
