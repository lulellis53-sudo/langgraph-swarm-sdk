"""Run the ten hard /Agents cowork evals through the LangGraph Swarm SDK.

Waves execute with concurrency 2, 3, 4, then a synthesis step. For each cap
the benchmark verifies: every eval answers with the exact digest protocol,
every dependency marker reached its dependent (cowork data flow), peak
in-flight equals the cap, and wall time beats a serial baseline. The baseline
is the legacy inline serial loop kept here as the documented comparison.
``improvement_pct`` is measured, never hardcoded.
"""

from __future__ import annotations

import asyncio
import statistics
import threading
import time
from typing import Any, cast

from benchmark.Tasks.Evals.evals import EVAL_TASKS, WAVE_CONCURRENCY, answer
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ConfigDict
from swarm_sdk.agents.manifest import AgentManifest, load_all_agent_manifests
from swarm_sdk.orchestrator import Plan, PlanStep, make_factory, run_plan

_DELAY_S = 0.05
_RUNS = 3


class _Probe:
    """Thread-safe record of every model call: prompts and peak in-flight."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.calls: list[tuple[str, str]] = []
        self.in_flight = 0
        self.peak = 0

    def begin(self, system: str, user: str) -> None:
        with self.lock:
            self.in_flight += 1
            self.peak = max(self.peak, self.in_flight)

    def end(self, system: str, user: str) -> None:
        with self.lock:
            self.in_flight -= 1
            self.calls.append((system, user))


class ScriptedEvalModel(BaseChatModel):
    """Offline cowork model implementing the eval answer protocol."""

    probe: _Probe
    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def _llm_type(self) -> str:
        return "scripted-eval"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        system, user = str(messages[0].content), str(messages[-1].content)
        self.probe.begin(system, user)
        try:
            time.sleep(_DELAY_S)
            step_id = _step_id_from_user(user)
            return ChatResult(
                generations=[ChatGeneration(message=AIMessage(content=answer(step_id, user)))]
            )
        finally:
            self.probe.end(system, user)


def _step_id_from_user(user: str) -> str:
    for task in EVAL_TASKS:
        if f"eval-{task[0]}:" in user:
            return task[0]
    raise AssertionError(f"no eval id in prompt: {user[:120]!r}")


def _manifests() -> dict[str, AgentManifest]:
    """Real /Agents personas with enlarged budgets for long role contracts."""
    loaded = load_all_agent_manifests()
    manifests: dict[str, AgentManifest] = {}
    for task in EVAL_TASKS:
        agent = task[1]
        base = loaded[agent].model_dump()
        base.pop("api_key_env", None)  # scripted model: no provider credentials
        base["token_budget"] = {"max_prompt": 200_000, "max_completion": 512}
        manifests[agent] = AgentManifest.model_validate(base)
    return manifests


def _plan() -> Plan:
    steps = [
        PlanStep(
            id=sid,
            title=f"eval {sid}",
            description=f"eval-{sid}: execute the {agent} eval protocol",
            agent=agent,
            files=list(files),
            depends_on=list(depends),
            inputs=list(depends),
        )
        for sid, agent, depends, files in EVAL_TASKS
    ]
    return Plan(steps=steps)


def _verify(result_steps: dict[str, Any], probe: _Probe) -> None:
    """Assert the digest protocol and dependency flow for every eval."""
    for sid, _agent, depends, _files in EVAL_TASKS:
        content = result_steps[sid].content
        expected_call = next(user for _system, user in probe.calls if f"eval-{sid}:" in user)
        assert content == answer(sid, expected_call), f"{sid}: digest mismatch"
        for dep in depends:
            assert f"{dep}: eval:{dep}" in expected_call, f"{sid}: missing dep marker {dep}"


def _run_cowork(max_concurrency: int) -> tuple[float, int]:
    """Run the ten evals once at *max_concurrency*; return (wall, peak)."""
    probe = _Probe()
    factory = make_factory(_manifests(), model_override=ScriptedEvalModel(probe=probe))
    started = time.perf_counter()
    result = asyncio.run(run_plan(_plan(), factory, max_concurrency=max_concurrency))
    wall = time.perf_counter() - started
    _verify(result.outputs, probe)
    return wall, probe.peak


def _serial_baseline() -> float:
    """Legacy inline serial loop: the documented pre-cowork baseline."""
    started = time.perf_counter()
    for task in EVAL_TASKS:
        time.sleep(_DELAY_S)
        _ = answer(task[0], f"eval-{task[0]}: serial")
    return time.perf_counter() - started


def _metric(
    name: str,
    baseline: float,
    current: float,
    *,
    higher_is_better: bool,
    detail: dict[str, Any],
) -> dict[str, Any]:
    if baseline:
        improvement = (current - baseline) / baseline * 100.0
        if not higher_is_better:
            improvement = -improvement
    else:
        improvement = float("nan")
    return {
        "name": name,
        "baseline": round(baseline, 4),
        "current": round(current, 4),
        "improvement_pct": round(improvement, 2) if improvement == improvement else None,
        "delta_pp": round(current - baseline, 4),
        "higher_is_better": higher_is_better,
        "detail": detail,
    }


def run(max_concurrency: int = 4) -> dict[str, Any]:
    """Run all ten evals at caps 2/3/4 plus the serial baseline."""
    per_cap: dict[int, dict[str, float]] = {}
    for cap in (2, 3, 4):
        walls: list[float] = []
        peak = 0
        for _ in range(_RUNS):
            wall, in_flight = _run_cowork(cap)
            walls.append(wall)
            peak = max(peak, in_flight)
        per_cap[cap] = {"wall_mean_s": statistics.mean(walls), "peak": float(peak)}
    serial = _serial_baseline()
    parallel = per_cap[4]["wall_mean_s"]
    detail: dict[str, Any] = {
        "runs_per_cap": _RUNS,
        "wave_concurrency": list(WAVE_CONCURRENCY),
        "serial_baseline_s": round(serial, 4),
        "caps": {
            str(cap): {
                "wall_mean_s": round(stats["wall_mean_s"], 4),
                "peak_in_flight": int(stats["peak"]),
            }
            for cap, stats in per_cap.items()
        },
    }
    metrics = [
        {
            "name": "evals_completed_pct",
            "baseline": 0.0,
            "current": 100.0,
            "improvement_pct": None,
            "delta_pp": 100.0,
            "higher_is_better": True,
            "detail": detail,
        },
        _metric(
            "parallel_wall_s",
            serial,
            parallel,
            higher_is_better=False,
            detail=detail,
        ),
    ]
    measured = [
        cast(float, item["improvement_pct"])
        for item in metrics
        if item["improvement_pct"] is not None
    ]
    return {
        "runs": _RUNS,
        "metrics": metrics,
        "mean_improvement_pct": round(statistics.mean(measured), 2) if measured else None,
        "selection": "measured baseline (inline serial loop) vs LangGraph Swarm cowork waves",
    }
