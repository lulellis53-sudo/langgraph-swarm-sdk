"""Golden agent-routing cases and gates (tune here; reviewed by humans)."""

from __future__ import annotations

# Candidates mirror ``SKILLS.md`` agent names (PascalCase as in manifests).
SWARM_AGENT_CANDIDATES: tuple[str, ...] = (
    "Planner",
    "Researcher",
    "Coder",
    "Tester",
    "Debugger",
    "Documenter",
    "DevOps",
    "Security",
    "DataEngineer",
    "Caching",
    "MLSpecialist",
    "Optimizer",
    "Reviewer",
)

# Minimum fraction of golden goals that must map to the labeled agent (local fallback).
MIN_ROUTING_ACCURACY = 0.85

# Local Jev Choice fallback budget (matches router docstring).
MAX_CHOICE_P50_MS = 35.0

# Below this confidence, routing should escalate (confirm / second agent), not auto-spawn.
REVIEW_CONFIDENCE_BELOW = 0.60

# (goal, expected_agent) — one primary owner per task shape.
AGENT_ROUTING_CASES: tuple[tuple[str, str], ...] = (
    (
        "Decompose this release into parallel waves with explicit dependencies and owners.",
        "Planner",
    ),
    (
        "Investigate OpenCL lazy-dispatch options and synthesize evidence from docs only.",
        "Researcher",
    ),
    (
        "Refactor OpenCL math into swarm_sdk/opencl with lazy GPU dispatch; "
        "keep gpu/ re-exports and fix failing dispatcher tests.",
        "Coder",
    ),
    (
        "Write pytest unit tests and assert integration coverage for the spawn planner.",
        "Tester",
    ),
    (
        "Root-cause the CI traceback: spawn returns empty steps intermittently.",
        "Debugger",
    ),
    (
        "Update README and docstrings for the new opencl package layout.",
        "Documenter",
    ),
    (
        "Fix the pixi CI workflow and docker image for benchmark runs.",
        "DevOps",
    ),
    (
        "Run a security audit on vault key handling; check for credential leaks.",
        "Security",
    ),
    (
        "Build a qdrant ingest pipeline from sqlite exports for retrieval benchmarks.",
        "DataEngineer",
    ),
    (
        "Add Redis semantic cache invalidation and TTL policy for prompt index hits.",
        "Caching",
    ),
    (
        "Evaluate faiss vs opencl vector store accuracy for embedding recall@10.",
        "MLSpecialist",
    ),
    (
        "Profile OpenCL vs CPU matmul on AMD 5300M and tune batch sizes for lazy_dispatcher.",
        "Optimizer",
    ),
    (
        "Review the OpenCL refactor pull request diff for race conditions before merge.",
        "Reviewer",
    ),
)
