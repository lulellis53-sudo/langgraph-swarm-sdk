"""Ten hard cowork evals for the /Agents swarm, executed in waves of 2, 3, 4, 1.

Every eval is executed by its specialist persona through the LangGraph Swarm
SDK (``Plan`` -> dependency waves -> ``WorkerAgent``). An eval is hard because
it is checked end to end: the scripted model must answer with the exact
protocol ``eval:<step_id>|d:<digest>`` where ``digest`` is blake2b of the exact
packed prompt it received. Any input mixing between parallel siblings, a lost
wave barrier, a dropped dependency, or a mutated prompt fails the eval
deterministically — no LLM required (scripted, offline).
"""

from __future__ import annotations

import hashlib

WAVE_CONCURRENCY: tuple[int, ...] = (2, 3, 4, 1)

#: (step_id, agent, depends_on, files) — files are disjoint within each wave.
EVAL_TASKS: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("T1", "Researcher", (), ("evals/t1_survey.md",)),
    ("T2", "Security", (), ("evals/t2_threats.md",)),
    ("T3", "Coder", ("T1",), ("evals/t3_impl.py",)),
    ("T4", "Tester", ("T2",), ("evals/t4_tests.py",)),
    ("T5", "DataEngineer", ("T1", "T2"), ("evals/t5_pipeline.py",)),
    ("T6", "Reviewer", ("T3", "T4"), ("evals/t6_review.md",)),
    ("T7", "Debugger", ("T3",), ("evals/t7_triage.md",)),
    ("T8", "DevOps", ("T4", "T5"), ("evals/t8_pipeline.yaml",)),
    ("T9", "Optimizer", ("T5",), ("evals/t9_profile.md",)),
    ("T10", "Documenter", ("T6", "T7", "T8", "T9"), ("evals/t10_docs.md",)),
)


def digest(text: str) -> str:
    """blake2b digest prefix used by the eval answer protocol."""
    return hashlib.blake2b(text.encode("utf-8"), digest_size=8).hexdigest()


def answer(step_id: str, prompt: str) -> str:
    """The deterministic eval answer for a packed prompt."""
    return f"eval:{step_id}|d:{digest(prompt)}"


def dep_marker(step_id: str) -> str:
    """Marker a dependency's answer must contribute to a dependent prompt."""
    return f"{step_id}: eval:{step_id}"
