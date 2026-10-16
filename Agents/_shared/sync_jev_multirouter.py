#!/usr/bin/env python3
"""Inject the shared Jev multirouter section into Agents/**/AGENTS.md (idempotent)."""

from __future__ import annotations

import re
from pathlib import Path

AGENTS_ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {"antigravity-imported", "benchmark", "tests", "_test", "_shared"}

ROLE_BRANCH: dict[str, str] = {
    "Orchestrator": "After CHOICE, stay Layer 5 coordination only — decompose, assign, merge; never implement.",
    "Planner": "CHOICE → Planner: emit JSON task graph; disjoint Coder `files` per wave.",
    "Researcher": "CHOICE → Researcher: read-only DARS; hand off implementation to Coder.",
    "Coder": "CHOICE → Coder: DARS §2 SWE — failing test first, manifest `files` only.",
    "Tester": "CHOICE → Tester: tests and coverage; do not own full refactors (Coder does).",
    "Debugger": "CHOICE → Debugger: reproduce → root cause; minimal fix or hand off to Coder.",
    "Reviewer": "CHOICE → Reviewer: diff/PR audit; read-only on production code.",
    "Documenter": "CHOICE → Documenter: docs and docstrings; no behavior changes unless asked.",
    "DevOps": "CHOICE → DevOps: CI, pixi, containers; no feature code.",
    "Security": "CHOICE → Security: audit and gates; Noul may still block exfil patterns in code.",
    "DataEngineer": "CHOICE → DataEngineer: pipelines, stores, ingest.",
    "Caching": "CHOICE → Caching: Redis / semantic cache policy.",
    "MLSpecialist": "CHOICE → MLSpecialist: models, embeddings, evaluation.",
    "Optimizer": "CHOICE → Optimizer: profile, ΔJEV, benchmark-backed tuning.",
    "Judge": "CHOICE → Judge: rubric + mechanical gates; Jev tie-break for `judge_models` only.",
    "ModelDelegate": "Layers 4–5: registry route / fallback / GPU embed-math; no task implementation.",
    "Router": "Layer 4 only: `route_task` from registry; no LLM execution.",
    "FallbackResolver": "Layer 4: next registry route after breaker; never retry same provider.",
    "Embedder": "Layer 4: GPU/CPU embedding dispatch.",
    "MathWorker": "Layer 4: GPU/CPU math dispatch and verify.",
    "RAG": "After multirouter, Topic 2 multiflow retrieval tree (cache → hybrid → rerank).",
    "DeepResearch": "CHOICE → research dossier; read-only until Documenter/Writer handoff.",
    "DeepWebSearch": "CHOICE → web research; untrusted page text; cite URLs.",
    "WebResearcher": "CHOICE → bounded web synthesis; hand off claims to Researcher/Judge.",
    "Benchmarket": "CHOICE → Benchmarket: harnesses under benchmark tasks; measured Δ% only.",
    "Refactor": "CHOICE → Refactor: structural refactors with AST workflow ASCII in reports.",
    "Investigator": "CHOICE → Investigator: read-only RE; facts vs hypotheses; cite evidence.",
}

COMPACT_MULTIROUTER = """\
```text
[inbound] → L0 denylist → L1 Noul → L2 Choice → L3 Score → L4 registry → L5 this persona
                 |fail       |no         |conf<0.60→MR2 rewind / Orchestrator confirm
```"""

JEV_HEADER = "## Jev multirouter"


def _shared_prefix(agent_dir: Path) -> str:
    depth = len(agent_dir.relative_to(AGENTS_ROOT).parts)
    return "/".join([".."] * depth) + "/_shared"


def jev_section(agent_name: str, shared: str) -> str:
    """Build the markdown block for one persona."""
    branch = ROLE_BRANCH.get(
        agent_name,
        f"CHOICE → **{agent_name}**: run this persona's decision tree only when Layer 2 selected `{agent_name}`.",
    )
    return f"""\
## Jev multirouter

{COMPACT_MULTIROUTER}

Swarm-wide flow (code denylist → Noul → Choice → Score → registry → persona):
[`{shared}/JEV_MULTIROUTER.md`]({shared}/JEV_MULTIROUTER.md).

Reflect, backward rewinds (MR2–MR4 / D2–D4), and autolearn buffer:
[`{shared}/JEV_REFLECT_AUTOLEARN.md`]({shared}/JEV_REFLECT_AUTOLEARN.md).

**This persona:** {branch}

**Before `done`:** run the four-item self-reflection checklist in JEV_REFLECT_AUTOLEARN.md; on failure, rewind (max 2), never repeat the same action unchanged.

"""


def inject_jev(content: str, agent_name: str, agent_dir: Path) -> str:
    """Insert or refresh the Jev multirouter section."""
    block = jev_section(agent_name, _shared_prefix(agent_dir))
    if JEV_HEADER in content:
        pattern = re.compile(
            r"\n## Jev multirouter\n.*?(?=\n## |\Z)",
            re.DOTALL,
        )
        return pattern.sub("\n" + block.rstrip() + "\n\n", content, count=1)
    anchors = (
        "## Operating principles",
        "## Decision tree",
        "## 1. Scope",
        "## Persona",
        "## Summary",
        "## Tasks",
        "## Responsibilities",
        "## Task Workflow",
    )
    for anchor in anchors:
        if anchor in content:
            idx = content.index(anchor)
            end = content.find("\n## ", idx + len(anchor))
            insert_at = end if end != -1 else len(content)
            return content[:insert_at] + "\n\n" + block + content[insert_at:]
    return block + content


def _agent_label(path: Path) -> str:
    parent = path.parent
    if parent.parent.name == "ModelDelegate" and parent.name != "ModelDelegate":
        return f"ModelDelegate/{parent.name}"
    return parent.name


def _persona_paths() -> list[Path]:
    paths: list[Path] = []
    for pattern in ("**/AGENTS.md", "**/agents.md"):
        for path in sorted(AGENTS_ROOT.glob(pattern)):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if path.parent.name in SKIP_DIRS:
                continue
            if path.name == "AGENTS.md" and path.parent == AGENTS_ROOT:
                continue
            paths.append(path)
    return paths


def main() -> None:
    """Update every persona contract under ``Agents/``."""
    changed = 0
    for path in _persona_paths():
        label = _agent_label(path)
        lookup = label if label in ROLE_BRANCH else path.parent.name
        original = path.read_text(encoding="utf-8")
        updated = inject_jev(original, lookup, path.parent)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            changed += 1
            print(f"updated {path.relative_to(AGENTS_ROOT.parent)}")
    print(f"done: {changed} files")


if __name__ == "__main__":
    main()
