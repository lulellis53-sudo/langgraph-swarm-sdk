---
name: OptimizerSkill
description: JEV score tuning, AST prompt compression, workflow graph mutation, AsyncIO concurrency optimization, and profiling skill for Optimizer agent.
---

# Optimizer Skill Guide

> **Purpose**: Provide JEV parameter calibration, AST prompt compression algorithms, workflow mutation procedures, and AsyncIO event loop concurrency tuning for **Optimizer**.

---

## 1. JEV Weight Matrix by Effort Level

| Effort Level | Value Weight ($V$) | Cost Weight ($\lambda$) | Latency Weight ($\mu$) | Exploration ($\gamma$) |
| :--- | :--- | :--- | :--- | :--- |
| **LOW** | $1.0$ | $0.40$ | $0.40$ | $0.05$ |
| **MEDIUM** | $1.0$ | $0.25$ | $0.25$ | $0.10$ |
| **HIGH** | $1.0$ | $0.10$ | $0.20$ | $0.15$ |

---

## 2. Workflow Graph Mutation Rules
1. **Parallel Fan-Out**: Convert sequential agent chains into parallel execution nodes when inputs are independent.
2. **AST Prompt Pruning**: Remove redundant system prompt instructions while keeping mechanical gates intact.
3. **Rollback Safety**: Revert any graph mutation that yields $\Delta\text{JEV} \le 0$ or breaks unit tests.

---

## 3. AsyncIO Concurrency Optimization Engine (AsyncOptimizer)

### 3.1 TaskGroup Concurrency Pattern
```python
import asyncio

async def fetch_item(item_id: int) -> dict:
    # Bounded async worker
    await asyncio.sleep(0.01)
    return {"id": item_id, "status": "ok"}

async def process_batch(item_ids: list[int], max_concurrency: int = 8) -> list[dict]:
    semaphore = asyncio.Semaphore(max_concurrency)
    results = []

    async def worker(item_id: int):
        async with semaphore:
            res = await fetch_item(item_id)
            results.append(res)

    async with asyncio.TaskGroup() as tg:
        for iid in item_ids:
            tg.create_task(worker(iid))

    return results
```

### 3.2 Offloading Synchronous Blocking I/O
```python
import asyncio

def blocking_heavy_calc(data: bytes) -> str:
    # CPU heavy computation
    return f"processed_{len(data)}"

async def async_wrapper(data: bytes) -> str:
    # Offload to worker thread pool without blocking event loop
    return await asyncio.to_thread(blocking_heavy_calc, data)
```
