"""Tests validating MathWorker manifest and role contract standards."""

from __future__ import annotations

from pathlib import Path

from swarm_sdk.agents.manifest import load_agent_manifest

_MATH_WORKER = Path(__file__).resolve().parents[3] / "Agents" / "ModelDelegate" / "MathWorker"


def test_math_worker_manifest_spec() -> None:
    manifest = load_agent_manifest(_MATH_WORKER / "agent.yaml")
    assert manifest.name == "ModelDelegate/MathWorker"
    assert manifest.role == "delegate_math"
    task_ids = {t.id for t in manifest.tasks}
    assert {"delegate_math", "solve_math", "verify_math"} <= task_ids
    assert {"gpu_math", "symbolic_math", "registry_lookup"} <= set(manifest.capabilities)
    assert {"numerical_optimization", "statistical_analysis", "proof_verification"} <= set(
        manifest.capabilities
    )
    assert manifest.token_budget.max_prompt >= 4096
    assert manifest.token_budget.max_completion >= 2048


def test_dispatch_contract_fields_are_preserved() -> None:
    manifest = load_agent_manifest(_MATH_WORKER / "agent.yaml")
    delegate = next(t for t in manifest.tasks if t.id == "delegate_math")
    assert {"selected_route", "gpu_enabled", "backend"} <= set(delegate.outputs)


def test_contract_documents_both_modes_and_crossover() -> None:
    text = (_MATH_WORKER / "AGENTS.md").read_text(encoding="utf-8")
    for needle in ("dispatch", "solve", "verify", "8,192", "SymPy", "LaTeX", "notes"):
        assert needle in text, needle
    assert "256x256" not in text  # the old, hardware-contradicting threshold
