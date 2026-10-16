#!/usr/bin/env python3
"""Inject AgentMethods / TEMPLATE ASCII workflow into Agents/**/AGENTS.md (idempotent)."""

from __future__ import annotations

import re
from pathlib import Path

AGENTS_ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {"antigravity-imported", "benchmark", "tests", "_test", "_shared"}

# From AgentMethods.md §3 function-to-method matrix (one primary method per role).
ROLE_METHOD: dict[str, str] = {
    "Orchestrator": "Primary: **DARS Router** — L1–L4 gate, assign tasks, merge handoffs.",
    "Planner": "Primary: **DARS Router** — decompose goals; JSON plan; dependency waves.",
    "Coder": "Primary: **SWE** — Specify → Locate → Test-First → Implement → Verify → Diff Review.",
    "Tester": "Primary: **SWE** (test leg) — reproduce, assert, coverage; no production refactors alone.",
    "Reviewer": "Primary: **Read-only ReAct** — AST/diff → reachability → evidence gate.",
    "Researcher": "Primary: **Corrective RAG** — decompose → retrieve → cite; read-only.",
    "Debugger": "Primary: **ReAct** — reproduce → observe → minimal fix or hand off to Coder.",
    "Documenter": "Primary: **Self-Refine** — rubric + claim ledger for docs.",
    "DevOps": "Primary: **HITL approval gate** — preview command, bounds, idempotency.",
    "Security": "Primary: **Read-only ReAct** + security rubric; no silent fixes.",
    "DataEngineer": "Primary: **Disposable plan-execute** — EXPLAIN, copy test, rollback path.",
    "Caching": "Primary: **SWE** (config leg) — cache policy, TTL, invalidation tests.",
    "MLSpecialist": "Primary: **ACT protocol** — anchor metrics, oracle checks.",
    "Optimizer": "Primary: **Evaluator-optimizer** — measure → mutate → re-benchmark.",
    "Judge": "Primary: **Self-Refine** — rubric, claim ledger, reflection rewinds (B1–B4).",
    "RAG": "Primary: **Corrective RAG** — cache → hybrid retrieve → rerank → CRAG recovery.",
    "DeepResearch": "Primary: **Corrective RAG** + dossier template; read-only.",
    "DeepWebSearch": "Primary: **ReAct** — search → fetch → cite; untrusted page text.",
    "WebResearcher": "Primary: **Corrective RAG** — bounded web synthesis.",
    "Benchmarket": "Primary: **SWE** (harness leg) — measured benchmarks only.",
    "Refactor": "Primary: **SWE** — behavior-preserving refactors + regression proof.",
    "Investigator": "Primary: **ReAct** — acquire → reverse-engineer → substantiate; read-only.",
    "ModelDelegate": "Primary: **DARS Router** (model lane) — registry route, no task execution.",
    "Router": "Primary: **DARS Router** — `route_task` from registry only.",
    "FallbackResolver": "Primary: **DARS Router** — next route after breaker.",
    "Embedder": "Primary: **DARS Router** — GPU/CPU embedding dispatch.",
    "MathWorker": "Primary: **ACT protocol** — dispatch, solve, verify.",
}

WORKFLOW_ASCII = """\
```text
[Intake: goal, scope, limits, acceptance criteria]
                    |
                    v
         +----------------------+
         | Clear, permitted,    |
         | in role?             |
         +----------+-----------+
              No   |   Yes
              v    v
           blocker  +----------------------+
                    | DARS classify L1–L4  |
                    +----------+-----------+
                               |
              +----------------+----------------+
              | L4 ask/block | L1 local | L2/L3 deep
              v              v          v
         +----------------------------------------+
         | Vertical: retrieval | math | code |   |
         | review | database | SWE | specialist |
         +--------------------+-------------------+
                              |
                              v
         +----------------------------------------+
         | Execute: direct | chain | parallel |  |
         | orchestrator | ReAct observe-act      |
         +--------------------+-------------------+
                              |
                              v
         +----------------------------------------+
         | Domain verify (tests, audit, oracle) |
         +--------------------+-------------------+
                    pass |          | fail
                         v          v
                    handoff JSON   Reflection:
                                   one fix, rerun
                                   same check (max 2)
                                   -> else blocked
```"""

SECTION_HEADER = "## Agentic workflow"
OLD_HEADERS = ("## Jev multirouter", "## Agentic workflow")


def _doc_prefix(agent_dir: Path) -> str:
    depth = len(agent_dir.relative_to(AGENTS_ROOT).parts)
    return "/".join([".."] * depth)


def workflow_section(agent_name: str, prefix: str) -> str:
    method = ROLE_METHOD.get(
        agent_name,
        f"Primary: **DARS + ReAct** — follow this persona's decision tree when scope matches `{agent_name}`.",
    )
    return f"""\
## Agentic workflow

Source: [`{prefix}/AgentMethods.md`]({prefix}/AgentMethods.md) · [`{prefix}/TEMPLATE.md`]({prefix}/TEMPLATE.md)

{WORKFLOW_ASCII}

**This persona:** {method}

**Backward / reflection:** failed check → classify (missing evidence | wrong plan | wrong route) → rewind to earliest wrong stage → one bounded fix → rerun the **same** check. Max **2** rewinds, then `blocked` / `needs_input` with evidence.

"""


def inject(content: str, agent_name: str, agent_dir: Path) -> str:
    block = workflow_section(agent_name, _doc_prefix(agent_dir))
    for header in OLD_HEADERS:
        if header in content:
            pattern = re.compile(
                rf"\n{re.escape(header)}\n.*?(?=\n## |\Z)",
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
        return parent.name
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
    changed = 0
    for path in _persona_paths():
        label = _agent_label(path)
        lookup = label if label in ROLE_METHOD else label
        original = path.read_text(encoding="utf-8")
        updated = inject(original, lookup, path.parent)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            changed += 1
            print(f"updated {path.relative_to(AGENTS_ROOT.parent)}")
    print(f"done: {changed} files")


if __name__ == "__main__":
    main()
