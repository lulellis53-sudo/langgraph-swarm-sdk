# ruff: noqa: E501
#!/usr/bin/env python3
# ruff: noqa: E501
"""Inject TEMPLATE-aligned sections into Agents/*/AGENTS.md (idempotent).

Does not inject the TEMPLATE map blockquote — persona leads each contract.
"""

from __future__ import annotations

import re
from pathlib import Path

AGENTS_ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {"antigravity-imported", "benchmark", "tests", "_shared"}

OPERATING = """\
## Operating principles

Follow [`../_shared/COMMON.md`](../_shared/COMMON.md#operating-principles). Role-specific rules below override only where stated.

"""

VALIDATION = """\
## Validation

[`../_shared/COMMON.md`](../_shared/COMMON.md#validation) — record commands in output `test_commands` / `checks`. Error recovery: [shared loop](../_shared/COMMON.md#error-recovery).

"""

TOOLS = """\
## Tools and permissions

[`../_shared/COMMON.md`](../_shared/COMMON.md#tools-and-permissions) plus this manifest’s `capabilities` in [`agent.yaml`](agent.yaml).

"""

COMPLETION = """\
## Completion checklist

Local pre/post checklists above **plus** [`../_shared/COMMON.md`](../_shared/COMMON.md#completion-checklist).

"""

PYTHON_MODULES = """\
## Python modules

When this persona writes Python, follow [`../_shared/COMMON.md`](../_shared/COMMON.md#python-modules).

"""

STATIC_SECTION = re.compile(
    r"\n## Static Templates\n\n(?:- .*\n)+\n?",
    re.MULTILINE,
)
PYTHON_TOPIC_H2 = re.compile(
    r"\n## Topic: Python Static Template\n\n.*?(?=\n## |\Z)",
    re.DOTALL,
)
PYTHON_TOPIC = re.compile(
    r"\n---\n\n## Topic: Python Static Template\n\n.*?(?=\n## |\Z)",
    re.DOTALL,
)
CURSOR_BOILERPLATE = re.compile(
    r"\n(?:For new Python modules[^\n]*\n|[-*] New Python modules:[^\n]*\n|[-*] .*\.cursor/[^\n]*\n)",
    re.MULTILINE,
)
def capabilities_table(yaml_path: Path) -> str:
    if not yaml_path.is_file():
        return ""
    text = yaml_path.read_text(encoding="utf-8")
    caps: list[str] = []
    in_caps = False
    for line in text.splitlines():
        if line.strip().startswith("capabilities:"):
            in_caps = True
            continue
        if in_caps:
            if line.startswith("  - "):
                caps.append(line.strip()[2:].strip())
            elif line and not line.startswith(" "):
                break
            elif line.strip() and not line.startswith("  "):
                break
    if not caps:
        return ""
    rows = "\n".join(f"| `{c}` | Per task scope | See role constraints |" for c in caps)
    return f"\n| Capability | Use | Restrictions |\n| --- | --- | --- |\n{rows}\n\n"


def inject_operating_after_persona(content: str) -> str:
    if "## Operating principles" in content:
        return content
    if "## Persona" not in content:
        return content
    # Insert after first ## Persona section (until next ## at same level)
    match = re.search(r"(## Persona\n(?:.*?\n)*?)(?=## )", content, re.DOTALL)
    if match:
        insert_at = match.end()
        return content[:insert_at] + OPERATING + content[insert_at:]
    # Persona is last section before EOF — unlikely
    for anchor in (
        "## Decision tree",
        "## Task decision tree",
        "## Multipath workflow",
        "## Workflow",
        "## Tasks",
        "## Responsibilities",
        "## Summary",
    ):
        if anchor in content:
            return content.replace(anchor, OPERATING + anchor, 1)
    return content


def normalize_python_sections(content: str) -> str:
    content = STATIC_SECTION.sub("\n" + PYTHON_MODULES, content)
    content = PYTHON_TOPIC_H2.sub("\n" + PYTHON_MODULES, content)
    content = PYTHON_TOPIC.sub("\n", content)
    content = CURSOR_BOILERPLATE.sub("\n", content)
    if "## Python modules" not in content and "## Constraints" in content:
        content = content.replace("## Constraints", PYTHON_MODULES + "## Constraints", 1)
    return content


def inject(path: Path) -> bool:
    content = path.read_text(encoding="utf-8")
    original = content
    agent_dir = path.parent

    content = normalize_python_sections(content)
    content = inject_operating_after_persona(content)

    yaml_path = agent_dir / "agent.yaml"
    cap_block = capabilities_table(yaml_path)

    if "## Validation" not in content or "COMMON.md#validation" not in content:
        for anchor in ("## Output contract", "## Methods of actuation", "## Constraints"):
            if anchor in content and "## Validation\n\n[`../_shared/COMMON.md`]" not in content:
                content = content.replace(anchor, VALIDATION + anchor, 1)
                break

    if "## Tools and permissions" not in content or "COMMON.md#tools-and-permissions" not in content:
        insert_at = "## Validation"
        if insert_at in content and "## Tools and permissions\n\n[`../_shared/COMMON.md`]" not in content:
            tools = TOOLS + (cap_block if cap_block else "")
            content = content.replace(insert_at, tools + insert_at, 1)

    if "## Completion checklist" not in content or "(TEMPLATE §10)" in content:
        content = content.replace("## Completion checklist (TEMPLATE §10)", "## Completion checklist", 1)
    if "## Completion checklist\n\nLocal" not in content and "## Completion checklist" not in content:
        for anchor in ("## Constraints", "## Python modules", "## Safety"):
            if anchor in content:
                content = content.replace(anchor, COMPLETION + anchor, 1)
                break

    if content != original:
        path.write_text(content, encoding="utf-8")
        return True
    return False


def main() -> None:
    changed = 0
    for path in sorted(AGENTS_ROOT.glob("*/AGENTS.md")):
        if path.parent.name in SKIP_DIRS:
            continue
        if inject(path):
            changed += 1
            print(f"updated {path.relative_to(AGENTS_ROOT.parent)}")
    print(f"done: {changed} files")


if __name__ == "__main__":
    main()
